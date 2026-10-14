"""Trip lifecycle: booking, assignment, pickup, ride, completion, cancellation and ratings."""

import secrets
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from django.db import IntegrityError, transaction
from django.db.models import Avg, F
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.roles import Cap
from apps.core.conf import (
    arrival_radius_meters,
    dispatch_max_radius_km,
    dispatch_mode,
    free_cancellation_seconds,
    request_timeout_seconds,
    upfront_distance_tolerance,
    upfront_duration_tolerance,
)
from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    DomainError,
    InvalidStateTransition,
)
from apps.drivers import goals
from apps.drivers.models import Availability, DriverProfile, Vehicle
from apps.drivers.services import nearby_available_drivers, recompute_safety_score
from apps.geo import geohash
from apps.geo.distance import haversine_km
from apps.geo.routing import RouteEstimate, eta_minutes
from apps.geo.services import require_city
from apps.notifications.models import Level
from apps.notifications.services import notify, notify_role
from apps.payments import services as payments
from apps.payments.models import PaymentMethod
from apps.pricing import passes
from apps.pricing import services as pricing
from apps.pricing.fare import with_boost
from apps.pricing.models import RideType
from apps.realtime import broadcast
from apps.riders.models import RiderProfile

from . import dispatch
from .models import (
    CAR_ONLY_PREFERENCES,
    TERMINAL_STATUSES,
    CancelledBy,
    OfferStatus,
    PricingMode,
    RatingDirection,
    RidePreference,
    ScheduledRide,
    ScheduledRideStatus,
    Trip,
    TripEvent,
    TripFlag,
    TripMessage,
    TripPaymentStatus,
    TripRating,
    TripStatus,
)
from .workflow import assert_transition

MIN_TRIP_KM = 0.3
MAX_TRIP_KM = 80
ROUTE_DEVIATION_FACTOR = Decimal("1.5")
RATING_WINDOW_DAYS = 7
TIP_WINDOW_HOURS = 48
RATING_SAMPLE = 100


# --- Helpers -----------------------------------------------------------------------------


def generate_otp() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def record_event(
    trip: Trip,
    kind: str,
    *,
    from_status: str = "",
    to_status: str = "",
    actor=None,
    message: str = "",
    data: dict | None = None,
    at: datetime | None = None,
) -> TripEvent:
    return TripEvent.objects.create(
        trip=trip,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        message=message[:255],
        data=data or {},
        created_at=at or timezone.now(),
    )


def stop_payload(trip) -> dict | None:
    if trip.stop_lat is None:
        return None
    return {"lat": trip.stop_lat, "lng": trip.stop_lng, "address": trip.stop_address}


def trip_payload(trip: Trip) -> dict:
    """Public trip state pushed to everyone watching (never includes the ride PIN)."""
    driver = trip.driver
    vehicle = trip.vehicle
    return {
        "id": trip.pk,
        "trip_number": trip.trip_number,
        "status": trip.status,
        "status_label": trip.get_status_display(),
        "city": trip.city_id,
        "ride_type": trip.ride_type.name,
        "pickup": {"lat": trip.pickup_lat, "lng": trip.pickup_lng, "address": trip.pickup_address},
        "dropoff": {
            "lat": trip.dropoff_lat,
            "lng": trip.dropoff_lng,
            "address": trip.dropoff_address,
        },
        "stop": stop_payload(trip),
        "driver": (
            {
                "id": driver.pk,
                "name": driver.name,
                "rating": driver.rating,
                "lat": driver.current_lat,
                "lng": driver.current_lng,
            }
            if driver
            else None
        ),
        "vehicle": str(vehicle) if vehicle else None,
        "pickup_eta_min": trip.pickup_eta_min,
        "estimated_fare": trip.estimated_fare,
        "fare_total": trip.fare_total,
        "surge": trip.surge_multiplier,
        "boost": trip.boost_amount,
    }


def _change_status(
    trip: Trip, to_status: str, *, actor=None, at: datetime, message: str = "", **fields
) -> Trip:
    assert_transition(trip.status, to_status)
    previous = trip.status
    trip.status = to_status
    for name, value in fields.items():
        setattr(trip, name, value)
    trip.save()
    record_event(
        trip,
        "STATUS",
        from_status=previous,
        to_status=to_status,
        actor=actor,
        message=message,
        at=at,
    )
    broadcast.trip_event(trip.pk, "status", trip_payload(trip))
    broadcast.ops_event(
        "trip_status",
        {
            "trip_id": trip.pk,
            "status": to_status,
            "city": trip.city_id,
            "lat": trip.pickup_lat,
            "lng": trip.pickup_lng,
        },
    )
    return trip


def _set_availability(driver: DriverProfile, availability: str) -> None:
    DriverProfile.objects.filter(pk=driver.pk).update(
        availability=availability, updated_at=timezone.now()
    )
    driver.availability = availability


def _lock(trip: Trip) -> Trip:
    return (
        Trip.objects.select_for_update(of=("self",))
        .select_related("rider__user", "driver__user", "ride_type", "city")
        .get(pk=trip.pk)
    )


def _require_driver(trip: Trip, driver: DriverProfile) -> None:
    if trip.driver_id != driver.pk:
        raise ActionNotPermitted("You are not the driver on this trip.")


def _q(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Booking -----------------------------------------------------------------------------


def _validate_points(city, pickup, dropoff, stop=None) -> None:
    if not city.contains(*dropoff):
        raise BusinessRuleViolation(
            f"The drop location is outside our {city.name} service area.", field="dropoff"
        )
    if stop is not None:
        if not city.contains(*stop):
            raise BusinessRuleViolation(
                f"The stop is outside our {city.name} service area.", field="stop"
            )
        if min(haversine_km(*stop, *pickup), haversine_km(*stop, *dropoff)) < 0.1:
            raise BusinessRuleViolation(
                "The stop is right next to your pickup or drop.", field="stop"
            )
    distance = haversine_km(*pickup, *dropoff)
    if distance < MIN_TRIP_KM:
        raise BusinessRuleViolation("Pickup and drop are too close together.", field="dropoff")
    if distance > MAX_TRIP_KM:
        raise BusinessRuleViolation(f"Trips are limited to {MAX_TRIP_KM} km.", field="dropoff")


def estimate_options(
    *,
    rider: RiderProfile | None,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    promo_code: str = "",
    at: datetime | None = None,
    stop: tuple[float, float] | None = None,
) -> dict:
    """Fare and pickup ETA for every ride type, as shown on the booking screen."""
    at = at or timezone.now()
    city = require_city(*pickup)
    _validate_points(city, pickup, dropoff, stop)
    has_pass = bool(rider and passes.active_pass(rider, at))
    options, promo_error = [], ""
    for ride_type in pricing.active_ride_types(city):
        promo = None
        if promo_code and rider:
            try:
                promo = pricing.validate_promo(
                    promo_code, rider=rider, city=city, ride_type=ride_type, now=at
                )
            except BusinessRuleViolation as exc:
                promo_error = exc.message
        estimate = pricing.estimate_fare(
            city=city,
            ride_type=ride_type,
            pickup=pickup,
            dropoff=dropoff,
            at=at,
            promo=promo,
            stop=stop,
            ride_pass=has_pass,
        )
        nearest = nearby_available_drivers(
            lat=pickup[0],
            lng=pickup[1],
            radius_km=float(dispatch_max_radius_km()),
            ride_type=ride_type,
            now=at,
            limit=1,
        )
        options.append(
            {
                "ride_type": ride_type,
                "estimate": estimate,
                "pickup_eta_min": (
                    round(eta_minutes(nearest[0].current_lat, nearest[0].current_lng, *pickup, at))
                    if nearest
                    else None
                ),
            }
        )
    return {
        "city": city,
        "options": options,
        "promo_error": promo_error
        if promo_code and not any(o["estimate"].fare.discount for o in options)
        else "",
    }


@transaction.atomic
def request_trip(
    *,
    rider: RiderProfile,
    ride_type: RideType,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    payment_method: str,
    pickup_address: str = "",
    dropoff_address: str = "",
    promo_code: str = "",
    now: datetime | None = None,
    stop: tuple[float, float] | None = None,
    stop_address: str = "",
    tip: Decimal | int = 0,
    preferences: list[str] | tuple[str, ...] = (),
) -> Trip:
    now = now or timezone.now()
    tip = Decimal(tip or 0)
    preferences = clean_preferences(preferences, ride_type)
    if tip and not payments.MIN_TIP <= tip <= payments.MAX_TIP:
        raise BusinessRuleViolation(
            f"Tips must be between ₹{payments.MIN_TIP} and ₹{payments.MAX_TIP}.", field="tip"
        )
    if rider.is_blocked:
        raise ActionNotPermitted("Your account is blocked. Please contact support.")
    if payment_method not in PaymentMethod.values:
        raise BusinessRuleViolation("Choose a valid payment method.", field="payment_method")
    balance = payments.wallet_balance(rider.user)
    if balance < 0:
        raise BusinessRuleViolation(
            f"Please clear your pending dues of ₹{-balance:,.2f} before booking.",
            field="payment_method",
        )
    city = require_city(*pickup)
    _validate_points(city, pickup, dropoff, stop)
    promo = (
        pricing.validate_promo(promo_code, rider=rider, city=city, ride_type=ride_type, now=now)
        if promo_code
        else None
    )
    has_pass = passes.active_pass(rider, now) is not None
    estimate = pricing.estimate_fare(
        city=city,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=dropoff,
        at=now,
        promo=promo,
        stop=stop,
        ride_pass=has_pass,
    )
    if payment_method == PaymentMethod.WALLET and balance < estimate.fare.total + tip:
        raise BusinessRuleViolation(
            f"Your wallet balance (₹{balance:,.2f}) doesn't cover this fare.",
            field="payment_method",
        )
    try:
        with transaction.atomic():
            trip = Trip.objects.create(
                tip_pledged=tip,
                preferences=preferences,
                ride_pass_applied=has_pass,
                trip_number=_next_trip_number(now),
                rider=rider,
                ride_type=ride_type,
                city=city,
                pickup_zone=estimate.pickup_zone,
                dropoff_zone=estimate.dropoff_zone,
                pickup_lat=pickup[0],
                pickup_lng=pickup[1],
                pickup_address=pickup_address
                or (estimate.pickup_zone.name if estimate.pickup_zone else ""),
                pickup_geohash=geohash.encode(*pickup, precision=7),
                dropoff_lat=dropoff[0],
                dropoff_lng=dropoff[1],
                dropoff_address=dropoff_address
                or (estimate.dropoff_zone.name if estimate.dropoff_zone else ""),
                stop_lat=stop[0] if stop else None,
                stop_lng=stop[1] if stop else None,
                stop_address=stop_address[:255] if stop else "",
                otp=generate_otp(),
                payment_method=payment_method,
                promo=promo,
                estimated_distance_km=estimate.route.distance_km,
                estimated_duration_min=estimate.route.duration_minutes,
                surge_multiplier=estimate.surge_multiplier,
                estimated_fare=estimate.fare.total,
                fare_estimate=estimate.fare.to_dict(),
                route_polyline=estimate.route.polyline,
                route_source=estimate.route.source,
                requested_at=now,
                dispatch_deadline=now + timedelta(seconds=request_timeout_seconds()),
            )
    except IntegrityError as exc:
        raise ConflictError("You already have a trip in progress.") from exc
    record_event(
        trip,
        "STATUS",
        to_status=TripStatus.REQUESTED,
        actor=rider.user,
        message=f"{ride_type.name} requested · ₹{estimate.fare.total} upfront",
        at=now,
    )
    broadcast.ops_event(
        "trip_requested",
        {"trip_id": trip.pk, "city": city.pk, "lat": trip.pickup_lat, "lng": trip.pickup_lng},
    )
    if dispatch_mode() == "SEQUENTIAL":
        dispatch.dispatch_trip(trip, now=now)
    return trip


def _next_trip_number(now: datetime) -> str:
    from apps.core.sequences import next_reference

    return next_reference("TRP", year=timezone.localtime(now).year, width=7)


# --- Driver flow -------------------------------------------------------------------------


def assign_driver(trip: Trip, *, driver: DriverProfile, eta_minutes: float, now: datetime) -> Trip:
    """Called by ``dispatch.accept_offer`` with the trip row already locked."""
    driver = DriverProfile.objects.select_for_update().select_related("user").get(pk=driver.pk)
    if driver.availability != Availability.ONLINE:
        raise InvalidStateTransition("You need to be online to accept trips.")
    vehicle = Vehicle.objects.filter(driver=driver, is_active=True).first()
    try:
        with transaction.atomic():
            trip = _change_status(
                trip,
                TripStatus.DRIVER_ASSIGNED,
                actor=driver.user,
                at=now,
                message=f"{driver.name} accepted",
                driver=driver,
                vehicle=vehicle,
                assigned_at=now,
                pickup_eta_min=_q(eta_minutes),
            )
    except IntegrityError as exc:
        raise ConflictError("You're already on another trip.") from exc
    _set_availability(driver, Availability.ON_TRIP)
    notify(
        trip.rider.user,
        f"{driver.name} is on the way",
        f"{vehicle} · about {eta_minutes:.0f} min away · Ride PIN {trip.otp}",
        level=Level.SUCCESS,
        link=f"/ride/trips/{trip.pk}/",
    )
    return trip


@transaction.atomic
def mark_arrived(
    trip: Trip, *, driver: DriverProfile, now: datetime | None = None, enforce_distance: bool = True
) -> Trip:
    now = now or timezone.now()
    trip = _lock(trip)
    _require_driver(trip, driver)
    assert_transition(trip.status, TripStatus.DRIVER_ARRIVED)
    driver.refresh_from_db(fields=["current_lat", "current_lng"])
    if enforce_distance and driver.has_location:
        meters = (
            haversine_km(driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng)
            * 1000
        )
        if meters > arrival_radius_meters():
            raise BusinessRuleViolation(f"You're {meters:,.0f} m from the pickup point.")
    flags = list(trip.flags)
    if trip.pickup_eta_min is not None and trip.assigned_at:
        actual = (now - trip.assigned_at).total_seconds() / 60
        if actual > float(trip.pickup_eta_min) * 2 + 5 and TripFlag.LONG_PICKUP not in flags:
            flags.append(TripFlag.LONG_PICKUP)
    trip = _change_status(
        trip, TripStatus.DRIVER_ARRIVED, actor=driver.user, at=now, arrived_at=now, flags=flags
    )
    notify(
        trip.rider.user,
        "Your driver has arrived",
        f"Share your Ride PIN {trip.otp} to start the trip.",
        level=Level.INFO,
        link=f"/ride/trips/{trip.pk}/",
    )
    return trip


MAX_PIN_ATTEMPTS = 5


def start_trip(
    trip: Trip,
    *,
    driver: DriverProfile,
    otp: str = "",
    qr: str = "",
    now: datetime | None = None,
) -> Trip:
    """Start the ride by scanning the rider's QR code or entering their spoken PIN. Either
    proves the rider is in this car, so neither can be guessed: after MAX_PIN_ATTEMPTS wrong
    entries the trip is locked and the rider is alerted (the attempt count is committed before
    the error is raised). The driver must also be at the pickup, next to the rider's phone."""
    from . import pickup

    now = now or timezone.now()
    with transaction.atomic():
        trip = _lock(trip)
        _require_driver(trip, driver)
        assert_transition(trip.status, TripStatus.IN_PROGRESS)
        if trip.pin_attempts >= MAX_PIN_ATTEMPTS:
            raise ActionNotPermitted(
                "Too many wrong PINs. The rider has been alerted; contact support to continue."
            )
        pickup.assert_together(trip, now=now)
        valid = (
            pickup.start_code_valid(trip, qr, now=now)
            if qr
            else bool(otp) and secrets.compare_digest(str(otp).strip(), trip.otp)
        )
        if valid:
            from . import safety

            waited = max((now - trip.arrived_at).total_seconds() / 60, 0) if trip.arrived_at else 0
            trip = _change_status(
                trip,
                TripStatus.IN_PROGRESS,
                actor=driver.user,
                at=now,
                started_at=now,
                waiting_minutes=_q(waited),
                night_safe=safety.night_safe_for(trip, now),
            )
            trip_id = trip.pk
            transaction.on_commit(lambda: safety.share_with_contacts(trip_id, now=now))
            return trip
        trip.pin_attempts += 1
        trip.save(update_fields=["pin_attempts", "updated_at"])
        left = MAX_PIN_ATTEMPTS - trip.pin_attempts
        if not left:
            record_event(
                trip, "PIN_LOCKED", actor=driver.user, message="Too many wrong ride PINs", at=now
            )
            notify(
                trip.rider.user,
                "Your driver entered the wrong PIN 5 times",
                "If you're not in this car, don't share your PIN and tap SOS in the app.",
                level=Level.WARNING,
                link=f"/ride/trips/{trip.pk}/",
            )
    what = "That QR code isn't for this trip (or has expired)" if qr else "Incorrect ride PIN"
    raise BusinessRuleViolation(
        f"{what}. {left} {'try' if left == 1 else 'tries'} left."
        if left
        else f"{what}. The trip is now locked and the rider has been alerted.",
        field="qr" if qr else "otp",
    )


# A GPS jump longer than this, faster than any car could drive, isn't billed (spoofing apps and
# glitches teleport the phone; honest small steps are always counted).
GPS_JUMP_KM = 1.0
GPS_JUMP_KMH = 150.0


def _distance_from_pings(trip: Trip) -> tuple[Decimal | None, Decimal]:
    """Distance driven with the rider on board: from the pickup point along the GPS trail
    recorded after the trip started (the drive to the pickup isn't billed).

    Returns ``(billed_km, skipped_jump_km)``.
    """
    trail = list(
        trip.pings.filter(recorded_at__gte=trip.started_at)
        .order_by("recorded_at")
        .values_list("lat", "lng", "recorded_at")
    )
    if not trail:
        return None, Decimal(0)
    points = [(trip.pickup_lat, trip.pickup_lng, trip.started_at), *trail]
    billed = skipped = 0.0
    for (lat1, lng1, t1), (lat2, lng2, t2) in pairwise(points):
        km = haversine_km(lat1, lng1, lat2, lng2)
        hours = max((t2 - t1).total_seconds(), 1) / 3600
        if km > GPS_JUMP_KM and km / hours > GPS_JUMP_KMH:
            skipped += km
        else:
            billed += km
    return _q(billed), _q(skipped)


@transaction.atomic
def complete_trip(
    trip: Trip,
    *,
    driver: DriverProfile,
    now: datetime | None = None,
    actual_distance_km: Decimal | float | None = None,
    telemetry: dict | None = None,
    payer_reference: str = "",
) -> Trip:
    now = now or timezone.now()
    trip = _lock(trip)
    _require_driver(trip, driver)
    assert_transition(trip.status, TripStatus.COMPLETED)
    from . import safety

    safety.assert_can_complete(trip, driver, now=now)

    duration = _q(max((now - trip.started_at).total_seconds() / 60, 1))
    skipped_jumps = Decimal(0)
    if actual_distance_km is not None:
        distance = _q(float(actual_distance_km))
    else:
        measured, skipped_jumps = _distance_from_pings(trip)
        distance = measured or trip.estimated_distance_km

    upfront = distance <= trip.estimated_distance_km * upfront_distance_tolerance() and (
        duration <= trip.estimated_duration_min * upfront_duration_tolerance()
    )
    route = (
        RouteEstimate(trip.estimated_distance_km, trip.estimated_duration_min)
        if upfront
        else RouteEstimate(distance, duration)
    )
    airport = bool(
        (trip.pickup_zone and trip.pickup_zone.is_airport)
        or (trip.dropoff_zone and trip.dropoff_zone.is_airport)
    )

    def price(promo):
        return pricing.price_trip(
            city=trip.city,
            ride_type=trip.ride_type,
            route=route,
            surge_multiplier=trip.surge_multiplier,
            airport=airport,
            promo=promo,
            waiting_minutes=trip.waiting_minutes or Decimal(0),
            ride_pass=trip.ride_pass_applied,
        )

    fare = price(trip.promo)
    # The redemption is recorded only now; if the promo ran out meanwhile, drop it.
    if (
        trip.promo
        and fare.discount
        and pricing.redeem_promo(trip.promo, rider=trip.rider, trip=trip, amount=fare.discount)
        is None
    ):
        fare = price(None)
    if trip.boost_amount:
        fare = with_boost(fare, trip.boost_amount)

    flags = list(trip.flags)
    if distance > trip.estimated_distance_km * ROUTE_DEVIATION_FACTOR:
        flags.append(TripFlag.ROUTE_DEVIATION)
    if skipped_jumps:
        flags.append(TripFlag.GPS_JUMP)
    telemetry = telemetry or {}
    trip = _change_status(
        trip,
        TripStatus.COMPLETED,
        actor=driver.user,
        at=now,
        message=f"₹{fare.total} · {distance} km · {'upfront' if upfront else 're-priced'}",
        completed_at=now,
        actual_distance_km=distance,
        actual_duration_min=duration,
        pricing_mode=PricingMode.UPFRONT if upfront else PricingMode.METERED,
        fare_breakdown=fare.to_dict(),
        fare_total=fare.total,
        driver_earning=fare.driver_earning,
        platform_commission=fare.platform_commission,
        gst_amount=fare.gst,
        discount_amount=fare.discount,
        flags=flags,
        harsh_brakes=int(telemetry.get("harsh_brakes", 0)),
        harsh_accelerations=int(telemetry.get("harsh_accelerations", 0)),
        speeding_seconds=int(telemetry.get("speeding_seconds", 0)),
        night_distance_km=min(_q(float(telemetry.get("night_distance_km", 0))), distance),
    )
    trip.payment_status = payments.settle_trip(trip, payer_reference=payer_reference, now=now)
    trip.save(update_fields=["payment_status", "updated_at"])
    if trip.tip_pledged and trip.payment_status == TripPaymentStatus.PAID:
        _collect_pledged_tip(trip, payer_reference=payer_reference, now=now)
    if trip.payment_status == TripPaymentStatus.PAID:
        from . import invoices

        invoices.send_after_commit(trip)

    _set_availability(driver, Availability.ONLINE)
    DriverProfile.objects.filter(pk=driver.pk).update(completed_trips=F("completed_trips") + 1)
    goals.reward_goals(driver, now=now)
    goals.after_trip(driver, trip, now=now)
    RiderProfile.objects.filter(pk=trip.rider_id).update(completed_trips=F("completed_trips") + 1)
    if trip.rider.referred_by_id and not trip.rider.referral_rewarded_at:
        payments.grant_referral_bonus(trip.rider, now=now)
    recompute_safety_score(driver)
    notify(
        trip.rider.user,
        f"Trip complete · ₹{fare.total}",
        f"{trip.pickup_address} → {trip.dropoff_address}. "
        "Rate your driver and download the receipt.",
        level=Level.SUCCESS,
        link=f"/ride/trips/{trip.pk}/",
    )
    return trip


# --- Cancellation ------------------------------------------------------------------------


def _who_cancels(trip: Trip, user) -> str:
    if user.is_rider and trip.rider.user_id == user.pk:
        return CancelledBy.RIDER
    if user.is_driver and trip.driver and trip.driver.user_id == user.pk:
        return CancelledBy.DRIVER
    if user.has_capability(Cap.TRIPS_MANAGE):
        return CancelledBy.OPS
    raise ActionNotPermitted("You can't cancel this trip.")


@transaction.atomic
def cancel_trip(trip: Trip, *, user, reason: str = "", now: datetime | None = None) -> Trip:
    now = now or timezone.now()
    trip = _lock(trip)
    if trip.status in TERMINAL_STATUSES:
        raise InvalidStateTransition("This trip has already ended.")
    by = _who_cancels(trip, user)
    rule = pricing.fare_rule(trip.city, trip.ride_type)

    if by == CancelledBy.RIDER:
        if trip.status == TripStatus.IN_PROGRESS:
            raise InvalidStateTransition(
                "A trip in progress can't be cancelled. Use SOS or contact support."
            )
        late = trip.status == TripStatus.DRIVER_ARRIVED or (
            trip.status == TripStatus.DRIVER_ASSIGNED
            and (now - trip.assigned_at).total_seconds() > free_cancellation_seconds()
        )
        return _cancel(
            trip,
            by=by,
            reason=reason or "Cancelled by rider",
            fee=rule.cancellation_fee if late else Decimal(0),
            actor=user,
            now=now,
        )

    if by == CancelledBy.DRIVER:
        if trip.status == TripStatus.IN_PROGRESS:
            raise InvalidStateTransition("Complete the trip or contact support.")
        waited = (now - trip.arrived_at).total_seconds() / 60 if trip.arrived_at else 0
        if trip.status == TripStatus.DRIVER_ARRIVED and waited >= rule.free_wait_minutes + 2:
            return _cancel(
                trip,
                by=by,
                reason="Rider didn't show up",
                fee=rule.cancellation_fee,
                actor=user,
                now=now,
            )
        return _reassign(trip, reason=reason or "Driver cancelled", now=now)

    return _cancel(
        trip, by=by, reason=reason or "Cancelled by operations", fee=Decimal(0), actor=user, now=now
    )


def _cancel(trip: Trip, *, by: str, reason: str, fee: Decimal, actor, now: datetime) -> Trip:
    driver = trip.driver
    dispatch.withdraw_trip_offers(trip, now=now)
    trip = _change_status(
        trip,
        TripStatus.CANCELLED,
        actor=actor,
        at=now,
        message=reason,
        cancelled_at=now,
        cancelled_by=by,
        cancellation_reason=reason,
        cancellation_fee=fee,
        payment_status=TripPaymentStatus.PAID if fee else TripPaymentStatus.NOT_APPLICABLE,
    )
    if driver:
        _set_availability(driver, Availability.ONLINE)
    if fee:
        payments.charge_cancellation_fee(trip, fee, now=now)
    if by != CancelledBy.RIDER:
        notify(
            trip.rider.user,
            "Your trip was cancelled",
            reason + (f" A ₹{fee} cancellation fee applies." if fee else ""),
            level=Level.WARNING,
            link=f"/ride/trips/{trip.pk}/",
        )
    if driver and by != CancelledBy.DRIVER:
        notify(driver.user, f"{trip.trip_number} was cancelled", reason, level=Level.WARNING)
        broadcast.driver_event(driver.pk, "trip_cancelled", {"trip_id": trip.pk})
    return trip


def _reassign(trip: Trip, *, reason: str, now: datetime) -> Trip:
    driver = trip.driver
    trip = _change_status(
        trip,
        TripStatus.REQUESTED,
        actor=driver.user,
        at=now,
        message=f"{driver.name} cancelled: {reason}. Finding another driver.",
        driver=None,
        vehicle=None,
        assigned_at=None,
        arrived_at=None,
        pickup_eta_min=None,
        dispatch_deadline=now + timedelta(seconds=request_timeout_seconds()),
    )
    _set_availability(driver, Availability.ONLINE)
    DriverProfile.objects.filter(pk=driver.pk).update(cancelled_trips=F("cancelled_trips") + 1)
    notify(
        trip.rider.user,
        "Your driver cancelled",
        "Don't worry, we're finding you another driver at the same price.",
        level=Level.WARNING,
        link=f"/ride/trips/{trip.pk}/",
    )
    dispatch.redispatch(trip, now=now)
    return trip


def expire_request(trip: Trip, *, now: datetime) -> Trip:
    """Nobody accepted in time (the trip row must already be locked)."""
    dispatch.withdraw_trip_offers(trip, now=now)
    trip = _change_status(
        trip,
        TripStatus.NO_DRIVER_FOUND,
        at=now,
        message="No driver accepted in time",
        cancelled_at=now,
        cancelled_by=CancelledBy.SYSTEM,
        cancellation_reason="No driver accepted in time",
        payment_status=TripPaymentStatus.NOT_APPLICABLE,
    )
    notify(
        trip.rider.user,
        "No drivers available right now",
        "All nearby drivers are busy. Please try again in a few minutes.",
        level=Level.WARNING,
        link="/ride/",
    )
    return trip


# --- After the trip ----------------------------------------------------------------------


def _recompute_rating(profile, direction: str, lookup: dict) -> None:
    """Average of the most recent ratings, so drivers can recover from an early bad patch."""
    ratings = TripRating.objects.filter(direction=direction, **lookup)
    recent_ids = ratings.order_by("-created_at").values("pk")[:RATING_SAMPLE]
    average = TripRating.objects.filter(pk__in=recent_ids).aggregate(avg=Avg("stars"))["avg"]
    if average is None:
        return
    type(profile).objects.filter(pk=profile.pk).update(
        rating=Decimal(str(average)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        rating_count=ratings.count(),
    )


@transaction.atomic
def rate_trip(
    trip: Trip, *, user, stars: int, tags=(), comment: str = "", now: datetime | None = None
) -> TripRating:
    now = now or timezone.now()
    trip = _lock(trip)
    if trip.status != TripStatus.COMPLETED:
        raise InvalidStateTransition("Only completed trips can be rated.")
    if now - trip.completed_at > timedelta(days=RATING_WINDOW_DAYS):
        raise BusinessRuleViolation(f"Trips can be rated for {RATING_WINDOW_DAYS} days.")
    if user.is_rider and trip.rider.user_id == user.pk:
        direction = RatingDirection.RIDER_TO_DRIVER
    elif user.is_driver and trip.driver.user_id == user.pk:
        direction = RatingDirection.DRIVER_TO_RIDER
    else:
        raise ActionNotPermitted("You weren't on this trip.")
    if not 1 <= int(stars) <= 5:
        raise BusinessRuleViolation("Rate from 1 to 5 stars.", field="stars")
    try:
        with transaction.atomic():
            rating = TripRating.objects.create(
                trip=trip,
                direction=direction,
                stars=int(stars),
                tags=[t[:30] for t in tags][:6],
                comment=comment[:500],
                created_at=now,
            )
    except IntegrityError as exc:
        raise ConflictError("You've already rated this trip.") from exc

    if direction == RatingDirection.RIDER_TO_DRIVER:
        _recompute_rating(trip.driver, direction, {"trip__driver": trip.driver})
        trip.driver.refresh_from_db(fields=["rating", "rating_count"])
        if trip.driver.rating < Decimal("4.20") and trip.driver.rating_count >= 20:
            notify_role(
                Role.OPS_MANAGER,
                f"{trip.driver.name}'s rating fell to {trip.driver.rating}",
                "Review recent trips and consider coaching or suspension.",
                level=Level.WARNING,
                link=f"/ops/drivers/{trip.driver.pk}/",
            )
    else:
        _recompute_rating(trip.rider, direction, {"trip__rider": trip.rider})
    if int(stars) <= 2 and TripFlag.LOW_RATING not in trip.flags:
        trip.flags = [*trip.flags, TripFlag.LOW_RATING]
        trip.save(update_fields=["flags", "updated_at"])
    return rating


@transaction.atomic
def tip_driver(
    trip: Trip,
    *,
    user,
    amount: Decimal,
    method: str,
    idempotency_key: str = "",
    payer_reference: str = "",
    now: datetime | None = None,
) -> Trip:
    now = now or timezone.now()
    trip = _lock(trip)
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can tip on this trip.")
    if trip.status != TripStatus.COMPLETED:
        raise InvalidStateTransition("You can tip after the trip is complete.")
    if now - trip.completed_at > timedelta(hours=TIP_WINDOW_HOURS):
        raise BusinessRuleViolation(f"Tips can be added within {TIP_WINDOW_HOURS} hours.")
    payments.add_tip(
        trip,
        amount=Decimal(amount),
        method=method,
        idempotency_key=idempotency_key,
        payer_reference=payer_reference,
    )
    Trip.objects.filter(pk=trip.pk).update(tip_amount=F("tip_amount") + Decimal(amount))
    trip.refresh_from_db(fields=["tip_amount"])
    record_event(trip, "TIP", actor=user, message=f"₹{amount} tip", at=now)
    return trip


def trip_route(trip: Trip) -> list[list[float]]:
    return [list(p) for p in trip.pings.order_by("recorded_at").values_list("lat", "lng")]


def can_view_trip(user, trip: Trip) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_rider:
        return trip.rider.user_id == user.pk
    if user.is_driver:
        return trip.driver_id is not None and trip.driver.user_id == user.pk
    return user.has_capability(Cap.TRIPS_VIEW)


CHAT_STATUSES = (TripStatus.DRIVER_ASSIGNED, TripStatus.DRIVER_ARRIVED, TripStatus.IN_PROGRESS)


def message_payload(message: TripMessage) -> dict:
    return {
        "id": message.pk,
        "trip_id": message.trip_id,
        "sender": message.sender,
        "body": message.body,
        "created_at": message.created_at,
    }


def send_message(trip: Trip, *, user, body: str) -> TripMessage:
    """Chat between the rider and the driver while a trip is under way."""
    body = " ".join(body.split())[:500]
    if not body:
        raise BusinessRuleViolation("Write a message first.", field="body")
    if user.is_rider and trip.rider.user_id == user.pk:
        sender = TripMessage.Sender.RIDER
    elif user.is_driver and trip.driver_id and trip.driver.user_id == user.pk:
        sender = TripMessage.Sender.DRIVER
    else:
        raise ActionNotPermitted("Only the rider and the driver can chat on a trip.")
    if trip.status not in CHAT_STATUSES:
        raise InvalidStateTransition("Chat is open from when a driver is assigned until drop-off.")
    message = TripMessage.objects.create(trip=trip, sender=sender, author=user, body=body)
    broadcast.trip_event(trip.pk, "message", message_payload(message))
    return message


# --- Sharing -----------------------------------------------------------------------------

SHARE_LINK_GRACE = timedelta(hours=1)


def share_trip(trip: Trip, *, user) -> str:
    """The token for the trip's public tracking page (created on first use)."""
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can share their trip.")
    if trip.status in TERMINAL_STATUSES:
        raise InvalidStateTransition("This trip has ended.")
    if not trip.share_token:
        trip.share_token = secrets.token_urlsafe(18)
        trip.save(update_fields=["share_token", "updated_at"])
    return trip.share_token


def shared_trip_view(token: str, *, now: datetime | None = None) -> dict | None:
    """What someone following a shared link may see: no phone numbers, PIN, fare or rider
    details beyond a first name. Links stop working an hour after the trip ends."""
    now = now or timezone.now()
    trip = (
        Trip.objects.select_related("driver__user", "vehicle", "ride_type", "rider__user")
        .filter(share_token=token)
        .first()
    )
    if trip is None:
        return None
    ended_at = trip.completed_at or trip.cancelled_at
    if ended_at and now - ended_at > SHARE_LINK_GRACE:
        return None
    driver, vehicle = trip.driver, trip.vehicle
    live = trip.status not in TERMINAL_STATUSES and driver is not None
    return {
        "status": trip.status,
        "status_label": trip.get_status_display(),
        "rider_first_name": trip.rider.user.first_name,
        "ride_type": trip.ride_type.name,
        "ride_type_code": trip.ride_type.code,
        "pickup": {"lat": trip.pickup_lat, "lng": trip.pickup_lng, "address": trip.pickup_address},
        "dropoff": {
            "lat": trip.dropoff_lat,
            "lng": trip.dropoff_lng,
            "address": trip.dropoff_address,
        },
        "stop": stop_payload(trip),
        "route_polyline": trip.route_polyline,
        "driver": (
            {"first_name": driver.user.first_name, "rating": driver.rating} if driver else None
        ),
        # Make, model and plate: what family need to recognise the car.
        "vehicle": str(vehicle) if vehicle else None,
        "driver_location": (
            {"lat": driver.current_lat, "lng": driver.current_lng, "heading": driver.heading}
            if live and driver.current_lat is not None
            else None
        ),
        "started_at": trip.started_at,
        "completed_at": trip.completed_at,
        "cancelled_at": trip.cancelled_at,
    }


# --- Scheduled rides ---------------------------------------------------------------------

SCHEDULE_MIN_LEAD = timedelta(minutes=20)
SCHEDULE_MAX_AHEAD = timedelta(days=7)
# Request a driver this long before pickup time, so they arrive about on time.
SCHEDULE_DISPATCH_LEAD = timedelta(minutes=8)
# Give up on a ride that couldn't go out by this long after its pickup time.
SCHEDULE_GIVE_UP_AFTER = timedelta(minutes=15)
MAX_UPCOMING_SCHEDULED = 5


def schedule_ride(
    *,
    rider: RiderProfile,
    ride_type: RideType,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    payment_method: str,
    scheduled_for: datetime,
    pickup_address: str = "",
    dropoff_address: str = "",
    promo_code: str = "",
    now: datetime | None = None,
    stop: tuple[float, float] | None = None,
    stop_address: str = "",
) -> ScheduledRide:
    now = now or timezone.now()
    if rider.is_blocked:
        raise ActionNotPermitted("Your account is blocked. Please contact support.")
    if payment_method not in PaymentMethod.values:
        raise BusinessRuleViolation("Choose a valid payment method.", field="payment_method")
    if scheduled_for < now + SCHEDULE_MIN_LEAD:
        minutes = int(SCHEDULE_MIN_LEAD.total_seconds() // 60)
        raise BusinessRuleViolation(
            f"Schedule at least {minutes} minutes ahead, or book now.", field="scheduled_for"
        )
    if scheduled_for > now + SCHEDULE_MAX_AHEAD:
        raise BusinessRuleViolation("You can schedule up to 7 days ahead.", field="scheduled_for")
    upcoming = rider.scheduled_rides.filter(status=ScheduledRideStatus.SCHEDULED)
    if upcoming.count() >= MAX_UPCOMING_SCHEDULED:
        raise BusinessRuleViolation(
            f"You can have up to {MAX_UPCOMING_SCHEDULED} scheduled rides at a time."
        )
    if upcoming.filter(
        scheduled_for__range=(
            scheduled_for - timedelta(minutes=30),
            scheduled_for + timedelta(minutes=30),
        )
    ).exists():
        raise ConflictError("You already have a ride scheduled around that time.")
    city = require_city(*pickup)
    _validate_points(city, pickup, dropoff, stop)
    promo = (
        pricing.validate_promo(promo_code, rider=rider, city=city, ride_type=ride_type, now=now)
        if promo_code
        else None
    )
    estimate = pricing.estimate_fare(
        city=city,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=dropoff,
        at=scheduled_for,
        promo=promo,
        stop=stop,
    )
    ride = ScheduledRide.objects.create(
        rider=rider,
        ride_type=ride_type,
        city=city,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        pickup_address=pickup_address[:255],
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        dropoff_address=dropoff_address[:255],
        stop_lat=stop[0] if stop else None,
        stop_lng=stop[1] if stop else None,
        stop_address=stop_address[:255] if stop else "",
        payment_method=payment_method,
        promo_code=promo_code,
        scheduled_for=scheduled_for,
        quoted_fare=estimate.fare.total,
    )
    local = timezone.localtime(scheduled_for)
    notify(
        rider.user,
        f"Ride scheduled for {local:%a %d %b, %I:%M %p}",
        f"{ride_type.name} to {dropoff_address or 'your destination'}. "
        "We'll find your driver a few minutes before pickup.",
        level=Level.SUCCESS,
        link="/ride/activity/",
    )
    return ride


def cancel_scheduled_ride(ride: ScheduledRide, *, user) -> ScheduledRide:
    if not (user.is_rider and ride.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can cancel their scheduled ride.")
    updated = ScheduledRide.objects.filter(pk=ride.pk, status=ScheduledRideStatus.SCHEDULED).update(
        status=ScheduledRideStatus.CANCELLED, updated_at=timezone.now()
    )
    if not updated:
        raise InvalidStateTransition("This ride has already gone out or been cancelled.")
    ride.refresh_from_db()
    return ride


def dispatch_scheduled_rides(*, now: datetime | None = None) -> dict:
    """Turn scheduled rides that are almost due into trip requests. Safe to run from several
    workers at once: each ride is claimed with SKIP LOCKED, so it's requested exactly once."""
    now = now or timezone.now()
    stats = {"dispatched": 0, "failed": 0}
    while True:
        with transaction.atomic():
            ride = (
                ScheduledRide.objects.select_for_update(skip_locked=True)
                .select_related("rider__user", "ride_type")
                .filter(
                    status=ScheduledRideStatus.SCHEDULED,
                    scheduled_for__lte=now + SCHEDULE_DISPATCH_LEAD,
                )
                .order_by("scheduled_for")
                .first()
            )
            if ride is None:
                return stats
            if ride.scheduled_for < now - SCHEDULE_GIVE_UP_AFTER:
                _fail_scheduled(ride, "The pickup time passed before a driver could be requested.")
                stats["failed"] += 1
                continue
            try:
                with transaction.atomic():
                    trip = request_trip(
                        rider=ride.rider,
                        ride_type=ride.ride_type,
                        pickup=(ride.pickup_lat, ride.pickup_lng),
                        dropoff=(ride.dropoff_lat, ride.dropoff_lng),
                        payment_method=ride.payment_method,
                        pickup_address=ride.pickup_address,
                        dropoff_address=ride.dropoff_address,
                        promo_code=ride.promo_code,
                        now=now,
                        stop=(ride.stop_lat, ride.stop_lng) if ride.stop_lat is not None else None,
                        stop_address=ride.stop_address,
                    )
            except DomainError as exc:
                _fail_scheduled(ride, exc.message)
                stats["failed"] += 1
                continue
            ride.status = ScheduledRideStatus.DISPATCHED
            ride.trip = trip
            ride.save(update_fields=["status", "trip", "updated_at"])
            notify(
                ride.rider.user,
                "Finding your driver",
                f"Your {timezone.localtime(ride.scheduled_for):%I:%M %p} ride "
                "is being matched now.",
                link=f"/ride/trips/{trip.pk}/",
            )
            stats["dispatched"] += 1


def _fail_scheduled(ride: ScheduledRide, reason: str) -> None:
    ride.status = ScheduledRideStatus.FAILED
    ride.failure_reason = reason[:255]
    ride.save(update_fields=["status", "failure_reason", "updated_at"])
    notify(
        ride.rider.user,
        "We couldn't book your scheduled ride",
        reason,
        level=Level.WARNING,
        link="/ride/book/",
    )


# --- Boost and tips while booking ----------------------------------------------------------

BOOST_STEPS = (Decimal(10), Decimal(20), Decimal(30), Decimal(50))
MAX_BOOST = Decimal(100)
BOOST_EXTRA_SEARCH = timedelta(seconds=60)


def boost_trip(trip: Trip, *, user, amount: Decimal | int, now: datetime | None = None) -> Trip:
    """Add money to a request that's still looking for a driver. It goes 100% to the driver,
    re-opens the request to drivers who passed, searches wider and gives it another minute."""
    from . import dispatch

    now = now or timezone.now()
    amount = Decimal(amount)
    with transaction.atomic():
        trip = _lock(trip)
        if not (user.is_rider and trip.rider.user_id == user.pk):
            raise ActionNotPermitted("Only the rider can boost their request.")
        if trip.status != TripStatus.REQUESTED:
            raise InvalidStateTransition("You can boost only while we're finding your driver.")
        if amount not in BOOST_STEPS:
            raise BusinessRuleViolation("Choose a boost of ₹10, ₹20, ₹30 or ₹50.", field="amount")
        total = trip.boost_amount + amount
        if total > MAX_BOOST:
            raise BusinessRuleViolation(
                f"Boosts are capped at ₹{MAX_BOOST} per ride.", field="amount"
            )
        fare = with_boost(trip.estimate, total)
        if trip.payment_method == PaymentMethod.WALLET:
            balance = payments.wallet_balance(trip.rider.user)
            if balance < fare.total + trip.tip_pledged:
                raise BusinessRuleViolation("Your wallet balance doesn't cover the boosted fare.")
        trip.boost_amount = total
        trip.boosted_at = now
        trip.dispatch_round += 1
        trip.fare_estimate = fare.to_dict()
        trip.estimated_fare = fare.total
        trip.dispatch_deadline = max(trip.dispatch_deadline, now) + BOOST_EXTRA_SEARCH
        trip.save(
            update_fields=[
                "boost_amount",
                "boosted_at",
                "dispatch_round",
                "fare_estimate",
                "estimated_fare",
                "dispatch_deadline",
                "updated_at",
            ]
        )
        record_event(
            trip, "BOOST", actor=user, message=f"+₹{amount} boost (₹{total} in all)", at=now
        )
        broadcast.trip_event(trip.pk, "status", trip_payload(trip))
        pending = trip.offers.filter(status=OfferStatus.PENDING).select_related("driver").first()
        if pending:
            # The driver looking at it right now sees the better offer at once.
            broadcast.driver_event(pending.driver_id, "offer", dispatch.offer_payload(pending))
    if not pending:
        dispatch.dispatch_trip(trip, now=now)
    trip.refresh_from_db()
    return trip


def _collect_pledged_tip(trip: Trip, *, payer_reference: str, now: datetime) -> None:
    """Collect the tip the rider promised at booking, the same way as the fare: cash in hand
    for cash rides, otherwise charged now. A failed charge never blocks the ride."""
    amount = trip.tip_pledged
    if trip.payment_method == PaymentMethod.CASH:
        message = f"₹{amount} tip (paid in cash)"
        notify(
            trip.driver.user, f"₹{amount} tip from your rider", "Collect it in cash with the fare."
        )
    else:
        try:
            payments.add_tip(
                trip, amount=amount, method=trip.payment_method, payer_reference=payer_reference
            )
        except BusinessRuleViolation as exc:
            notify(
                trip.rider.user, "Your tip couldn't be charged", exc.message, level=Level.WARNING
            )
            return
        message = f"₹{amount} tip (promised at booking)"
    Trip.objects.filter(pk=trip.pk).update(tip_amount=F("tip_amount") + amount)
    trip.tip_amount += amount
    record_event(trip, "TIP", actor=trip.rider.user, message=message, at=now)


# --- Ride preferences and favourite drivers ------------------------------------------------

TWO_WHEELERS_AND_AUTOS = {"BIKE", "AUTO"}


def clean_preferences(preferences, ride_type: RideType) -> list[str]:
    """Known preferences, once each; AC and luggage are dropped for bikes and autos."""
    chosen = []
    for value in preferences or ():
        if value not in RidePreference.values:
            raise BusinessRuleViolation(f"Unknown ride preference: {value}", field="preferences")
        if value in chosen:
            continue
        if value in CAR_ONLY_PREFERENCES and ride_type.code in TWO_WHEELERS_AND_AUTOS:
            continue
        chosen.append(value)
    return chosen


def set_favourite(trip: Trip, *, user, favourite: bool) -> bool:
    """Heart (or un-heart) the driver of a finished trip."""
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can save their driver.")
    if trip.driver_id is None or trip.status != TripStatus.COMPLETED:
        raise InvalidStateTransition("You can save a driver after a completed trip.")
    if favourite:
        trip.rider.favourite_drivers.add(trip.driver_id)
    else:
        trip.rider.favourite_drivers.remove(trip.driver_id)
    return favourite
