"""Tour packages: price, book, assign a driver ahead, run the day, cancel and rate.

* **Price** (fixed when booking): the whole route from the pickup through every stop and back,
  at the intercity per-km rate for the car (at least 80 km a day), plus time at the places, plus
  parking at each stop, the booking fee and GST. Multi-day tours add the driver's daily
  allowance (all of it goes to the driver), as on outstation trips. Ops can adjust a package's
  price by a percentage for the season.
* **Driver ahead**: a day before (or right away when the tour is that close), the best-rated
  available driver in the city with the right car, a road-worthy vehicle and intercity rides
  switched on is assigned. They can decline; the next one is asked.
* **On the day** the driver taps *Start tour*: it becomes an intercity round trip run by the
  normal trip machinery (PIN, live tracking, SOS, Ride Check, payment) at the booked price. If
  the assigned driver hasn't started 15 minutes before departure, the trip goes to normal
  dispatch at the same price. The driver marks each stop reached and left; the rider and their
  trusted contacts see the itinerary live.
* **Cancel**: free until 24 hours before departure; after that 25% of the price (the assigned
  driver keeps their share). Once started, the trip's own cancellation rules apply.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.conf import intercity_terms, platform_commission_percent
from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    InvalidStateTransition,
)
from apps.core.sequences import next_reference
from apps.geo.distance import haversine_km
from apps.geo.services import require_city
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.payments.models import PaymentMethod
from apps.pricing.fare import FareBreakdown, FareLine
from apps.pricing.models import RideType, Service
from apps.rides.packages import ROAD_FACTOR, _booking_fee, _breakdown, _m

from .models import BookingStatus, TourBooking, TourCategory, TourPackage

TOUR_TYPES = ("MINI", "SEDAN", "SUV")
WAIT_PER_HOUR = {"MINI": Decimal(100), "SEDAN": Decimal(120), "SUV": Decimal(150)}
PARKING_PER_STOP = Decimal(50)
MIN_KM_PER_DAY = 80
HIGHWAY_KMH, CITY_KMH = 45, 22
BOOK_AHEAD_HOURS = 4  # the earliest departure is 4 hours from now
BOOK_WITHIN_DAYS = 60
ASSIGN_AHEAD = timedelta(hours=26)
FREE_CANCEL = timedelta(hours=24)
LATE_CANCEL_SHARE = Decimal("0.25")
FALLBACK_BEFORE = timedelta(minutes=15)


# --- Price -----------------------------------------------------------------------------------


def route(package: TourPackage, pickup: tuple[float, float] | None = None) -> dict:
    city = package.city
    start = pickup or (city.center_lat, city.center_lng)
    stops = list(package.stops.all())
    points = [start, *((s.lat, s.lng) for s in stops), start]
    km = (
        sum(Decimal(haversine_km(*points[i], *points[i + 1])) for i in range(len(points) - 1))
        * ROAD_FACTOR
    )
    speed = CITY_KMH if package.category == TourCategory.CITY else HIGHWAY_KMH
    drive = km / speed * 60
    visit = sum(s.minutes for s in stops)
    return {
        "km": _m(km),
        "drive_minutes": int(drive),
        "visit_minutes": visit,
        "hours": round(float(drive + visit) / 60, 1),
        "stops": len(stops),
    }


def tour_fare(
    package: TourPackage, ride_type: RideType, *, pickup: tuple[float, float] | None = None
) -> FareBreakdown:
    if ride_type.code not in TOUR_TYPES:
        raise BusinessRuleViolation("Tours are in cars: Mini, Sedan or SUV.", field="ride_type")
    terms = intercity_terms()
    city = package.city
    r = route(package, pickup)
    rate = terms["per_km"][ride_type.code] * Decimal(city.fare_multiplier)
    billed = max(r["km"], Decimal(MIN_KM_PER_DAY * package.days))
    wait_hours = Decimal(r["visit_minutes"]) / 60
    lines = [
        FareLine("TOUR", f"Tour route: {billed:.0f} km × ₹{rate:.2f}", _m(billed * rate), "FARE"),
        FareLine(
            "TOUR_TIME",
            f"Time at {r['stops']} places ({wait_hours:.1f} h)",
            _m(wait_hours * WAIT_PER_HOUR[ride_type.code]),
            "FARE",
        ),
    ]
    if package.price_adjust_percent:
        base = sum((line.amount for line in lines), Decimal(0))
        adjust = _m(base * package.price_adjust_percent / 100)
        label = "Season offer" if adjust < 0 else "Peak season"
        lines.append(
            FareLine("TOUR_SEASON", f"{label} ({package.price_adjust_percent:+d}%)", adjust, "FARE")
        )
    return _breakdown(
        lines,
        fees=_booking_fee(city, ride_type) + PARKING_PER_STOP * r["stops"],
        allowance=terms["allowance"] * package.days if package.days > 1 else Decimal(0),
        distance_km=r["km"],
        duration_minutes=Decimal(r["drive_minutes"] + r["visit_minutes"]),
    )


def quotes(package: TourPackage) -> list[dict]:
    from apps.pricing.models import FareRule

    open_types = set(
        FareRule.objects.filter(
            city=package.city, is_active=True, ride_type__code__in=TOUR_TYPES
        ).values_list("ride_type__code", flat=True)
    )
    out = []
    for ride_type in RideType.objects.filter(code__in=sorted(open_types)).order_by("seats", "pk"):
        fare = tour_fare(package, ride_type)
        out.append(
            {
                "ride_type": ride_type.code,
                "name": ride_type.name,
                "seats": ride_type.seats,
                "price": str(fare.total),
                "fare": fare.to_dict(),
            }
        )
    return out


# --- Book ------------------------------------------------------------------------------------


def book(
    *,
    rider,
    package: TourPackage,
    ride_type: RideType,
    depart_at: datetime,
    pickup: tuple[float, float],
    pickup_address: str = "",
    group_size: int = 1,
    payment_method: str = PaymentMethod.UPI,
    now: datetime | None = None,
) -> TourBooking:
    from apps.payments import services as payments

    now = now or timezone.now()
    if rider.is_blocked:
        raise ActionNotPermitted("Your account is blocked. Please contact support.")
    if not package.is_active:
        raise BusinessRuleViolation("This tour isn't running right now.")
    if depart_at < now + timedelta(hours=BOOK_AHEAD_HOURS):
        raise BusinessRuleViolation(
            f"Book at least {BOOK_AHEAD_HOURS} hours ahead so we can line up a driver.",
            field="depart_at",
        )
    if depart_at > now + timedelta(days=BOOK_WITHIN_DAYS):
        raise BusinessRuleViolation(
            f"Tours can be booked up to {BOOK_WITHIN_DAYS} days ahead.", field="depart_at"
        )
    if require_city(*pickup).pk != package.city_id:
        raise BusinessRuleViolation(
            f"This tour starts in {package.city.name}: choose a pickup there.", field="pickup"
        )
    if not 1 <= group_size <= ride_type.seats:
        raise BusinessRuleViolation(
            f"A {ride_type.name} seats {ride_type.seats}: choose a bigger car.", field="group_size"
        )
    if payment_method not in PaymentMethod.values:
        raise BusinessRuleViolation("Choose a valid payment method.", field="payment_method")
    if payments.wallet_balance(rider.user) < 0:
        raise BusinessRuleViolation("Please clear your pending dues before booking.")
    day = timezone.localdate(depart_at)
    if TourBooking.objects.filter(
        rider=rider,
        depart_at__date=day,
        status__in=[BookingStatus.BOOKED, BookingStatus.ASSIGNED, BookingStatus.STARTED],
    ).exists():
        raise ConflictError("You already have a tour that day.")
    fare = tour_fare(package, ride_type, pickup=pickup)
    booking = TourBooking.objects.create(
        reference=next_reference("TOUR", year=now.year, width=5),
        package=package,
        rider=rider,
        ride_type=ride_type,
        depart_at=depart_at,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        pickup_address=pickup_address[:255],
        group_size=group_size,
        payment_method=payment_method,
        fare=fare.to_dict(),
        price=fare.total,
        created_at=now,
    )
    notify(
        rider.user,
        f"{package.name} booked",
        f"{timezone.localtime(depart_at):%a %d %b, %I:%M %p} · ₹{fare.total:,.2f}. "
        "We'll confirm your driver the day before.",
        level=Level.SUCCESS,
        link="/ride/tours",
    )
    if depart_at - now <= ASSIGN_AHEAD:
        booking = assign(booking, now=now)
    return booking


# --- Assign a driver ahead ---------------------------------------------------------------------


def _busy_driver_ids(day: date) -> set[int]:
    return set(
        TourBooking.objects.filter(
            depart_at__date=day,
            status__in=[BookingStatus.ASSIGNED, BookingStatus.STARTED],
            driver__isnull=False,
        ).values_list("driver_id", flat=True)
    )


def candidates(booking: TourBooking):
    from apps.drivers.models import DriverProfile, OnboardingStatus, VehicleCondition

    return (
        DriverProfile.objects.filter(
            city_id=booking.package.city_id,
            onboarding_status=OnboardingStatus.APPROVED,
            accepts_intercity=True,
            vehicles__is_active=True,
            vehicles__ride_type=booking.ride_type,
            vehicles__condition=VehicleCondition.ACTIVE,
            vehicles__seats__gte=booking.group_size,
        )
        .exclude(pk__in=_busy_driver_ids(timezone.localdate(booking.depart_at)))
        .exclude(pk__in=booking.declined_by)
        .exclude(user__is_active=False)
        .order_by("-rating", "-completed_trips", "pk")
        .select_related("user")
        .distinct()
    )


@transaction.atomic
def assign(booking: TourBooking, *, now: datetime | None = None) -> TourBooking:
    now = now or timezone.now()
    booking = TourBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != BookingStatus.BOOKED:
        return booking
    driver = candidates(booking).first()
    if driver is None:
        return booking  # the sweep tries again; ops see it as unassigned
    booking.driver, booking.assigned_at, booking.status = driver, now, BookingStatus.ASSIGNED
    booking.save(update_fields=["driver", "assigned_at", "status"])
    when = f"{timezone.localtime(booking.depart_at):%a %d %b, %I:%M %p}"
    earning = Decimal(booking.fare["driver_earning"])
    notify(
        driver.user,
        f"Tour booked for you: {booking.package.name}",
        f"{when} · pickup {booking.pickup_address or 'see the app'} · you earn ₹{earning:,.0f}",
        level=Level.SUCCESS,
        link="/drive",
    )
    vehicle = driver.active_vehicle
    notify(
        booking.rider.user,
        f"Your driver for {booking.package.name}",
        f"{driver.name} ({driver.rating}★) in a {vehicle} will pick you up {when}.",
        level=Level.SUCCESS,
        link="/ride/tours",
    )
    return booking


def decline(booking: TourBooking, *, driver, now: datetime | None = None) -> TourBooking:
    with transaction.atomic():
        booking = TourBooking.objects.select_for_update().get(pk=booking.pk)
        if booking.driver_id != driver.pk or booking.status != BookingStatus.ASSIGNED:
            raise InvalidStateTransition("This tour isn't assigned to you.")
        booking.declined_by = [*booking.declined_by, driver.pk]
        booking.driver, booking.assigned_at, booking.status = None, None, BookingStatus.BOOKED
        booking.save(update_fields=["declined_by", "driver", "assigned_at", "status"])
    return assign(booking, now=now)  # the next driver in line


# --- The day of the tour ---------------------------------------------------------------------


def _create_trip(booking: TourBooking, *, now: datetime):
    """The tour as an intercity round trip at the booked price (the furthest stop is the
    trip's destination on the map)."""
    from apps.geo import geohash
    from apps.geo.services import zone_for_point
    from apps.rides.models import Trip, TripStatus
    from apps.rides.services import _next_trip_number, generate_otp, record_event

    package = booking.package
    stops = list(package.stops.all())
    pickup = (booking.pickup_lat, booking.pickup_lng)
    furthest = max(stops, key=lambda s: haversine_km(*pickup, s.lat, s.lng))
    fare = FareBreakdown.from_dict(booking.fare)
    try:
        with transaction.atomic():
            trip = Trip.objects.create(
                trip_number=_next_trip_number(now),
                service=Service.INTERCITY,
                rider=booking.rider,
                ride_type=booking.ride_type,
                city=package.city,
                pickup_zone=zone_for_point(package.city, *pickup),
                pickup_lat=pickup[0],
                pickup_lng=pickup[1],
                pickup_address=booking.pickup_address,
                pickup_geohash=geohash.encode(*pickup, precision=7),
                dropoff_lat=furthest.lat,
                dropoff_lng=furthest.lng,
                dropoff_address=f"{package.name} (round trip via {len(stops)} places)"[:255],
                otp=generate_otp(),
                payment_method=booking.payment_method,
                estimated_distance_km=fare.distance_km,
                estimated_duration_min=fare.duration_minutes,
                surge_multiplier=Decimal(1),
                estimated_fare=fare.total,
                fare_estimate=booking.fare,
                round_trip=True,
                trip_days=package.days,
                requested_at=now,
                dispatch_deadline=now + timedelta(minutes=20),
            )
    except IntegrityError as exc:
        raise ConflictError(
            "The traveller is on another ride right now; start the tour when it ends."
        ) from exc
    record_event(
        trip,
        "STATUS",
        to_status=TripStatus.REQUESTED,
        actor=booking.rider.user,
        message=f"Tour {booking.reference}: {package.name} · ₹{fare.total}",
        at=now,
    )
    booking.trip = trip
    booking.status = BookingStatus.STARTED
    booking.save(update_fields=["trip", "status"])
    return trip


@transaction.atomic
def start(booking: TourBooking, *, driver, lat: float, lng: float, now: datetime | None = None):
    """The assigned driver starts the tour: they go online and the trip is theirs."""
    from apps.drivers import services as drivers
    from apps.drivers.models import Availability
    from apps.rides.services import assign_driver

    now = now or timezone.now()
    booking = TourBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.driver_id != driver.pk:
        raise ActionNotPermitted("This tour is assigned to another driver.")
    if booking.status != BookingStatus.ASSIGNED:
        raise InvalidStateTransition("This tour can't be started now.")
    if not booking.depart_at - timedelta(hours=2) <= now <= booking.depart_at + timedelta(hours=2):
        raise BusinessRuleViolation("You can start the tour within 2 hours of departure.")
    driver.refresh_from_db()
    if driver.availability == Availability.OFFLINE:
        drivers.go_online(driver, lat=lat, lng=lng, now=now)
    elif driver.availability == Availability.ON_TRIP:
        raise ConflictError("Finish your current trip first.")
    trip = _create_trip(booking, now=now)
    eta = haversine_km(lat, lng, booking.pickup_lat, booking.pickup_lng) / 0.4  # ~24 km/h
    return assign_driver(trip, driver=driver, eta_minutes=eta, now=now)


def _fallback(booking: TourBooking, *, now: datetime) -> None:
    """The assigned driver hasn't started: give the trip to normal dispatch, same price."""
    from apps.rides import dispatch

    with transaction.atomic():
        booking = TourBooking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in (BookingStatus.BOOKED, BookingStatus.ASSIGNED):
            return
        missing = booking.driver
        try:
            trip = _create_trip(booking, now=now)
        except ConflictError:
            return  # the traveller is still on another ride: the next sweep tries again
    if missing is not None:
        notify(
            missing.user,
            f"Tour {booking.reference} went to another driver",
            "You hadn't started it 15 minutes before departure.",
            level=Level.WARNING,
        )
    from apps.rides.services import dispatch_mode

    if dispatch_mode() == "SEQUENTIAL":
        dispatch.dispatch_trip(trip, now=now)  # batch mode: the next sweep matches it


def mark_stop(booking: TourBooking, *, driver, order: int, event: str, now=None) -> TourBooking:
    """The driver reached (``arrived``) or left (``left``) a stop; the rider sees it live."""
    now = now or timezone.now()
    booking = TourBooking.objects.select_related("trip", "package", "rider__user").get(
        pk=booking.pk
    )
    if booking.driver_id != driver.pk and (booking.trip and booking.trip.driver_id != driver.pk):
        raise ActionNotPermitted("This isn't your tour.")
    if booking.status != BookingStatus.STARTED:
        raise InvalidStateTransition("Start the tour first.")
    if event not in ("arrived", "left"):
        raise BusinessRuleViolation("Unknown stop event.")
    if not booking.package.stops.filter(order=order).exists():
        raise BusinessRuleViolation("No such stop on this tour.")
    progress = dict(booking.progress)
    entry = dict(progress.get(str(order), {}))
    if event == "left" and "arrived" not in entry:
        raise BusinessRuleViolation("Mark the stop reached first.")
    entry.setdefault(event, now.isoformat())
    progress[str(order)] = entry
    TourBooking.objects.filter(pk=booking.pk).update(progress=progress)
    booking.progress = progress
    if event == "arrived":
        stop = booking.package.stops.get(order=order)
        notify(
            booking.rider.user,
            f"Reached {stop.name}",
            f"About {stop.minutes} minutes here. {stop.note}".strip(),
            level=Level.INFO,
            link="/ride/tours",
        )
    return booking


def on_trip_finished(trip) -> None:
    """Called when a trip completes or is cancelled: keep the booking in step."""
    from apps.rides.models import TripStatus

    booking = TourBooking.objects.filter(trip=trip).first()
    if booking is None:
        return
    if trip.status == TripStatus.COMPLETED:
        booking.status = BookingStatus.COMPLETED
        booking.driver_id = booking.driver_id or trip.driver_id
        booking.save(update_fields=["status", "driver"])
        notify(
            booking.rider.user,
            f"How was {booking.package.name}?",
            "Rate your tour to help other travellers.",
            level=Level.INFO,
            link="/ride/tours",
        )
    elif trip.status in (TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND):
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = trip.cancelled_at or timezone.now()
        booking.cancelled_by = trip.cancelled_by or "SYSTEM"
        booking.cancellation_fee = trip.cancellation_fee or 0
        booking.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_fee"])


def final_fare(trip) -> FareBreakdown | None:
    """A tour costs what was booked (``None``: not a tour, price it normally)."""
    booking = TourBooking.objects.filter(trip=trip).only("fare").first()
    return FareBreakdown.from_dict(booking.fare) if booking else None


# --- Cancel and rate ---------------------------------------------------------------------------


def cancel(booking: TourBooking, *, user, now: datetime | None = None) -> TourBooking:
    from apps.payments import accounts
    from apps.payments import services as payments
    from apps.payments.models import TransactionKind
    from apps.rides import services as rides

    now = now or timezone.now()
    staff = getattr(user, "is_staff_member", False) or user.is_staff
    if booking.rider.user_id != user.pk and not staff:
        raise ActionNotPermitted("You can only cancel your own tours.")
    if booking.status in (BookingStatus.COMPLETED, BookingStatus.CANCELLED):
        raise InvalidStateTransition("This tour has already ended.")
    if booking.trip_id:
        rides.cancel_trip(booking.trip, user=user, reason="Tour cancelled", now=now)
        booking.refresh_from_db()
        return booking
    by = "RIDER" if booking.rider.user_id == user.pk else "OPS"
    late = booking.depart_at - now < FREE_CANCEL
    fee = _m(booking.price * LATE_CANCEL_SHARE) if late and by == "RIDER" else Decimal(0)
    with transaction.atomic():
        booking = TourBooking.objects.select_for_update().get(pk=booking.pk)
        if fee:
            legs = [(payments.ensure_wallet(booking.rider.user), -fee)]
            if booking.driver_id:
                share = _m(fee * (100 - platform_commission_percent()) / 100)
                legs += [
                    (payments.ensure_wallet(booking.driver.user), share),
                    (accounts.PLATFORM_COMMISSION, fee - share),
                ]
            else:
                legs.append((accounts.PLATFORM_FEES, fee))
            payments.post(
                TransactionKind.CANCELLATION_FEE,
                legs,
                description=f"Late cancellation of tour {booking.reference}",
                actor=user,
                at=now,
            )
        booking.status, booking.cancelled_at = BookingStatus.CANCELLED, now
        booking.cancelled_by, booking.cancellation_fee = by, fee
        booking.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_fee"])
    if booking.driver_id:
        notify(
            booking.driver.user,
            f"Tour {booking.reference} cancelled",
            booking.package.name
            + (
                f" · you keep ₹{fee - _m(fee * platform_commission_percent() / 100):,.2f}"
                if fee
                else ""
            ),
            level=Level.WARNING,
        )
    return booking


def rate(booking: TourBooking, *, user, stars: int, review: str = "") -> TourBooking:
    if booking.rider.user_id != user.pk:
        raise ActionNotPermitted("Only the traveller can rate this tour.")
    if booking.status != BookingStatus.COMPLETED:
        raise InvalidStateTransition("Rate the tour after it ends.")
    if booking.rating is not None:
        raise ConflictError("You've already rated this tour.")
    if not 1 <= stars <= 5:
        raise BusinessRuleViolation("Choose 1 to 5 stars.", field="stars")
    TourBooking.objects.filter(pk=booking.pk).update(rating=stars, review=review[:300])
    TourPackage.objects.filter(pk=booking.package_id).update(
        rating_sum=F("rating_sum") + stars, rating_count=F("rating_count") + 1
    )
    booking.rating, booking.review = stars, review[:300]
    return booking


# --- The sweep (every few minutes) -----------------------------------------------------------


def sweep(*, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    assigned = fallen_back = 0
    for booking in TourBooking.objects.filter(
        status=BookingStatus.BOOKED, depart_at__lte=now + ASSIGN_AHEAD, depart_at__gt=now
    ).select_related("package"):
        if assign(booking, now=now).status == BookingStatus.ASSIGNED:
            assigned += 1
    for booking in TourBooking.objects.filter(
        status__in=[BookingStatus.BOOKED, BookingStatus.ASSIGNED],
        depart_at__lte=now + FALLBACK_BEFORE,
    ).select_related("package__city", "rider__user", "driver__user"):
        if booking.depart_at < now - timedelta(hours=3):
            booking.status, booking.cancelled_at, booking.cancelled_by = (
                BookingStatus.CANCELLED,
                now,
                "SYSTEM",
            )
            booking.save(update_fields=["status", "cancelled_at", "cancelled_by"])
            continue
        _fallback(booking, now=now)
        fallen_back += 1
    return {"assigned": assigned, "dispatched": fallen_back}
