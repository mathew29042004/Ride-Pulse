"""Hourly rentals and intercity trips: booked by the package or by distance, not by route.

* **Rental** (like Ola/Uber Rentals): a car and driver for 1, 2, 4 or 8 hours with 10 km per
  hour included. No fixed drop: the rider ends it wherever they are; extra km and minutes are
  added at the end.
* **Intercity** (like Ola Outstation): from a served city to anywhere 40–600 km away, one-way
  or a round trip over 1–7 days. Priced per km (at least 100 km one-way, 250 km a day on round
  trips) plus a daily driver allowance that's all the driver's. Tolls and parking are paid on
  the way.

Both are priced here (GST and commission like rides) and then run through the normal trip,
dispatch, payment and safety machinery.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.conf import (
    gst_rate,
    intercity_terms,
    platform_commission_percent,
    rental_terms,
    request_timeout_seconds,
)
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.geo import geohash
from apps.geo.distance import haversine_km
from apps.geo.services import zone_for_point
from apps.payments.models import PaymentMethod
from apps.pricing.fare import FareBreakdown, FareLine
from apps.pricing.models import RideType, Service

from .models import Trip, TripStatus

CENT = Decimal("0.01")
ROAD_FACTOR = Decimal("1.25")  # highway distance vs straight line
HIGHWAY_KMH = Decimal(45)
CAR_TYPES = ("MINI", "SEDAN", "SUV")


def _m(value) -> Decimal:
    return Decimal(value).quantize(CENT)


def _breakdown(
    fare_lines: list[FareLine],
    *,
    fees: Decimal,
    allowance: Decimal = Decimal(0),
    distance_km: Decimal,
    duration_minutes: Decimal,
) -> FareBreakdown:
    """Commission on the fare, GST on fare + fees; the driver allowance is all the driver's."""
    ride_fare = sum((line.amount for line in fare_lines), Decimal(0))
    commission = _m(ride_fare * platform_commission_percent() / 100)
    lines = list(fare_lines)
    if fees:
        lines.append(FareLine("BOOKING_FEE", "Booking fee", fees, "FEE"))
    taxable = ride_fare + fees
    gst = _m(taxable * gst_rate())
    lines.append(FareLine("GST", f"GST ({gst_rate() * 100:.0f}%)", gst, "TAX"))
    if allowance:
        lines.append(
            FareLine("ALLOWANCE", "Driver allowance (100% to your driver)", allowance, "BOOST")
        )
    return FareBreakdown(
        lines=lines,
        distance_km=_m(distance_km),
        duration_minutes=_m(duration_minutes),
        ride_fare=_m(ride_fare),
        fees=_m(fees),
        taxable=_m(taxable),
        gst=gst,
        total=_m(taxable + gst + allowance),
        driver_earning=_m(ride_fare - commission + allowance),
        platform_commission=commission,
    )


def _multiplier(city) -> Decimal:
    return Decimal(city.fare_multiplier)


def _booking_fee(city, ride_type) -> Decimal:
    from apps.pricing.services import fare_rule

    return Decimal(fare_rule(city, ride_type).booking_fee)


# --- Rentals --------------------------------------------------------------------------------


def rental_fare(
    city,
    ride_type: RideType,
    hours: int,
    *,
    used_km: Decimal | None = None,
    used_minutes: Decimal | None = None,
) -> FareBreakdown:
    terms = rental_terms()
    packages = dict(terms["packages"])
    if hours not in packages:
        raise BusinessRuleViolation("Choose a 1, 2, 4 or 8 hour package.", field="package_hours")
    rates = terms["rates"].get(ride_type.code)
    if rates is None:
        raise BusinessRuleViolation("Rentals are available in cars.", field="ride_type")
    km = packages[hours]
    scale = _multiplier(city)
    lines = [
        FareLine(
            "PACKAGE", f"{hours} h / {km} km package", _m(rates["hour"] * hours * scale), "FARE"
        )
    ]
    if used_km is not None and Decimal(used_km) > km:
        extra = Decimal(used_km) - km
        lines.append(
            FareLine(
                "EXTRA_KM", f"Extra {extra:.1f} km", _m(extra * rates["extra_km"] * scale), "FARE"
            )
        )
    if used_minutes is not None and Decimal(used_minutes) > hours * 60:
        extra = Decimal(used_minutes) - hours * 60
        lines.append(
            FareLine(
                "EXTRA_TIME",
                f"Extra {extra:.0f} min",
                _m(extra * rates["extra_min"] * scale),
                "FARE",
            )
        )
    return _breakdown(
        lines,
        fees=_booking_fee(city, ride_type),
        distance_km=Decimal(used_km if used_km is not None else km),
        duration_minutes=Decimal(used_minutes if used_minutes is not None else hours * 60),
    )


# --- Intercity --------------------------------------------------------------------------------


def intercity_distance(pickup, dropoff) -> Decimal:
    return _m(Decimal(haversine_km(*pickup, *dropoff)) * ROAD_FACTOR)


def intercity_fare(
    city,
    ride_type: RideType,
    distance_km: Decimal,
    *,
    round_trip: bool = False,
    days: int = 1,
    driven_km: Decimal | None = None,
) -> FareBreakdown:
    terms = intercity_terms()
    rate = terms["per_km"].get(ride_type.code)
    if rate is None:
        raise BusinessRuleViolation("Intercity trips are available in cars.", field="ride_type")
    if round_trip and not 1 <= days <= 7:
        raise BusinessRuleViolation("Round trips can be 1 to 7 days.", field="days")
    days = days if round_trip else 1
    route_km = distance_km * 2 if round_trip else distance_km
    minimum = terms["min_km_per_day"] * days if round_trip else terms["min_km_one_way"]
    billed = max(route_km, Decimal(minimum))
    if driven_km is not None and Decimal(driven_km) > billed * Decimal("1.1"):
        billed = Decimal(driven_km)  # took a much longer way: the extra km are charged
    rate = rate * _multiplier(city)
    label = "Round trip" if round_trip else "One way"
    lines = [
        FareLine("INTERCITY", f"{label}: {billed:.0f} km × ₹{rate:.2f}", _m(billed * rate), "FARE")
    ]
    hours = route_km / HIGHWAY_KMH * 60
    return _breakdown(
        lines,
        fees=_booking_fee(city, ride_type),
        allowance=terms["allowance"] * days,
        distance_km=route_km,
        duration_minutes=hours,
    )


# --- Quotes and booking ------------------------------------------------------------------------


def quotes(
    *,
    service: str,
    pickup: tuple[float, float],
    dropoff: tuple[float, float] | None = None,
    hours: int | None = None,
    round_trip: bool = False,
    days: int = 1,
    at: datetime | None = None,
) -> dict:
    """Prices and pickup ETAs for each car type (the booking screen)."""
    from apps.core.conf import dispatch_max_radius_km
    from apps.drivers.services import nearby_available_drivers

    from .services import eta_minutes, require_city

    at = at or timezone.now()
    city = require_city(*pickup)
    distance = _check_destination(city, pickup, dropoff) if service == Service.INTERCITY else None
    options = []
    for ride_type in RideType.objects.filter(code__in=CAR_TYPES, is_active=True).order_by(
        "sort_order"
    ):
        try:
            if service == Service.RENTAL:
                fare = rental_fare(city, ride_type, hours or 2)
            else:
                fare = intercity_fare(city, ride_type, distance, round_trip=round_trip, days=days)
        except BusinessRuleViolation:
            continue  # this car type isn't offered in the city right now (see pricing.coverage)
        nearest = _nearby(
            ride_type, service, pickup, at, nearby_available_drivers, dispatch_max_radius_km
        )
        options.append(
            {
                "ride_type": ride_type,
                "fare": fare,
                "pickup_eta_min": round(
                    eta_minutes(nearest[0].current_lat, nearest[0].current_lng, *pickup, at)
                )
                if nearest
                else None,
            }
        )
    return {
        "city": city,
        "distance_km": distance,
        "packages": [{"hours": h, "km": k} for h, k in rental_terms()["packages"]],
        "options": options,
    }


def _nearby(ride_type, service, pickup, at, nearby_available_drivers, radius):
    drivers = nearby_available_drivers(
        lat=pickup[0],
        lng=pickup[1],
        radius_km=float(radius()),
        ride_type=ride_type,
        now=at,
        limit=5,
    )
    if service == Service.INTERCITY:
        drivers = [d for d in drivers if d.accepts_intercity]
    return drivers


def _check_destination(city, pickup, dropoff) -> Decimal:
    if dropoff is None:
        raise BusinessRuleViolation("Where are you going?", field="dropoff")
    terms = intercity_terms()
    straight = haversine_km(*pickup, *dropoff)
    if city.contains(*dropoff) or straight < terms["min_km"]:
        raise BusinessRuleViolation(
            f"Intercity trips go at least {terms['min_km']} km out of {city.name}. "
            "Book a normal ride for trips in the city.",
            field="dropoff",
        )
    if straight > terms["max_km"]:
        raise BusinessRuleViolation(
            f"Intercity trips go up to {terms['max_km']} km.", field="dropoff"
        )
    return intercity_distance(pickup, dropoff)


def request_package_trip(
    *,
    rider,
    service: str,
    ride_type: RideType,
    pickup: tuple[float, float],
    payment_method: str,
    dropoff: tuple[float, float] | None = None,
    pickup_address: str = "",
    dropoff_address: str = "",
    hours: int | None = None,
    round_trip: bool = False,
    days: int = 1,
    now: datetime | None = None,
) -> Trip:
    from apps.payments import services as payments

    from . import dispatch
    from .services import (
        _next_trip_number,
        broadcast,
        dispatch_mode,
        generate_otp,
        record_event,
        require_city,
    )

    now = now or timezone.now()
    if rider.is_blocked:
        raise ActionNotPermitted("Your account is blocked. Please contact support.")
    if payment_method not in PaymentMethod.values:
        raise BusinessRuleViolation("Choose a valid payment method.", field="payment_method")
    city = require_city(*pickup)
    if service == Service.RENTAL:
        fare = rental_fare(city, ride_type, hours or 0)
        dropoff, dropoff_address = pickup, dropoff_address or "Ends where you finish"
        distance, km = (
            Decimal(dict(rental_terms()["packages"])[hours]),
            dict(rental_terms()["packages"])[hours],
        )
        duration = Decimal(hours * 60)
    elif service == Service.INTERCITY:
        distance = _check_destination(city, pickup, dropoff)
        fare = intercity_fare(city, ride_type, distance, round_trip=round_trip, days=days)
        km, duration = None, fare.duration_minutes
    else:
        raise BusinessRuleViolation("Choose a rental or an intercity trip.", field="service")
    balance = payments.wallet_balance(rider.user)
    if balance < 0:
        raise BusinessRuleViolation(
            f"Please clear your pending dues of ₹{-balance:,.2f} before booking.",
            field="payment_method",
        )
    if payment_method == PaymentMethod.WALLET and balance < fare.total:
        raise BusinessRuleViolation(
            f"Your wallet balance (₹{balance:,.2f}) doesn't cover this fare.",
            field="payment_method",
        )
    zones = list(city.zones.all())
    pickup_zone = zone_for_point(city, *pickup, zones)
    try:
        with transaction.atomic():
            trip = Trip.objects.create(
                trip_number=_next_trip_number(now),
                service=service,
                rider=rider,
                ride_type=ride_type,
                city=city,
                pickup_zone=pickup_zone,
                pickup_lat=pickup[0],
                pickup_lng=pickup[1],
                pickup_address=pickup_address or (pickup_zone.name if pickup_zone else ""),
                pickup_geohash=geohash.encode(*pickup, precision=7),
                dropoff_lat=dropoff[0],
                dropoff_lng=dropoff[1],
                dropoff_address=dropoff_address[:255],
                otp=generate_otp(),
                payment_method=payment_method,
                estimated_distance_km=distance,
                estimated_duration_min=_m(duration),
                surge_multiplier=Decimal(1),
                estimated_fare=fare.total,
                fare_estimate=fare.to_dict(),
                package_hours=hours if service == Service.RENTAL else None,
                package_km=km,
                round_trip=round_trip and service == Service.INTERCITY,
                trip_days=days if round_trip and service == Service.INTERCITY else 1,
                requested_at=now,
                dispatch_deadline=now + timedelta(seconds=request_timeout_seconds()),
            )
    except IntegrityError as exc:
        raise ConflictError("You already have a trip in progress.") from exc
    what = (
        f"{hours} h rental"
        if service == Service.RENTAL
        else f"Intercity {'round trip' if round_trip else 'one way'} · {distance:.0f} km"
    )
    record_event(
        trip,
        "STATUS",
        to_status=TripStatus.REQUESTED,
        actor=rider.user,
        message=f"{ride_type.name} {what} requested · ₹{fare.total}",
        at=now,
    )
    broadcast.ops_event(
        "trip_requested",
        {"trip_id": trip.pk, "city": city.pk, "lat": trip.pickup_lat, "lng": trip.pickup_lng},
    )
    if dispatch_mode() == "SEQUENTIAL":
        dispatch.dispatch_trip(trip, now=now)
    return trip


def final_fare(trip: Trip, *, distance: Decimal, duration: Decimal) -> FareBreakdown:
    """At the end: rentals add extra km and minutes; intercity charges big detours; a tour
    costs what was booked."""
    from apps.tours.services import final_fare as tour_fare

    booked = tour_fare(trip)
    if booked is not None:
        return booked
    if trip.service == Service.RENTAL:
        return rental_fare(
            trip.city, trip.ride_type, trip.package_hours, used_km=distance, used_minutes=duration
        )
    one_way = trip.estimated_distance_km / 2 if trip.round_trip else trip.estimated_distance_km
    return intercity_fare(
        trip.city,
        trip.ride_type,
        one_way,
        round_trip=trip.round_trip,
        days=trip.trip_days,
        driven_km=distance,
    )


def offer_details(trip: Trip) -> dict | None:
    """What a driver sees on the offer card."""
    if trip.service == Service.RENTAL:
        return {"kind": "RENTAL", "hours": trip.package_hours, "km": trip.package_km}
    if trip.service == Service.INTERCITY:
        return {
            "kind": "INTERCITY",
            "km": trip.estimated_distance_km,
            "round_trip": trip.round_trip,
            "days": trip.trip_days,
            "destination": trip.dropoff_address,
        }
    return None
