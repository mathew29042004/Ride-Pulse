"""Pickup verification: making sure the right rider gets into the right car.

* **Scan to start.** The rider's app shows a QR code; the driver scans it. The code is an HMAC
  of the trip, its secret ride PIN and the current 30-second window, so it changes every 30 s
  and a screenshot is useless a minute later. The spoken 4-digit PIN stays as the fallback.
* **The PIN is shown only when the driver is close** (arrived, or within 500 m), so it can't be
  passed on early.
* **Together at the pickup.** A trip only starts when the driver is at the pickup and, if the
  rider's phone shares its location, the two phones are within 150 m of each other.
* **Is this your car?** The rider confirms the plate; "no" alerts the safety desk at once.
* **Left behind / taken elsewhere.** After the start, if the rider's phone and the car end up
  more than 1 km apart, both are alerted (once) and the trip timeline records it.

Rider locations are only used when they're plausibly real: within 5 km of the pickup when first
reported. A phone somewhere else entirely (e.g. a laptop running the demo) is ignored, so it
can't trigger false alarms.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.conf import arrival_radius_meters
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.geo.distance import haversine_km
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import Trip, TripStatus

CODE_WINDOW_SECONDS = 30
PIN_REVEAL_KM = 0.5
TOGETHER_KM = 0.15
PLAUSIBLE_KM = 5.0
RIDER_FIX_FRESH = timedelta(minutes=2)
SEPARATION_KM = 1.0


# --- Who can see what ----------------------------------------------------------------------


def _driver_km_from_pickup(trip: Trip) -> float | None:
    driver = trip.driver
    if driver is None or driver.current_lat is None:
        return None
    return haversine_km(driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng)


def pin_visible(trip: Trip) -> bool:
    """The rider's PIN/QR appear once the driver has arrived or is within 500 m."""
    if trip.status == TripStatus.DRIVER_ARRIVED:
        return True
    if trip.status == TripStatus.DRIVER_ASSIGNED:
        km = _driver_km_from_pickup(trip)
        return km is not None and km <= PIN_REVEAL_KM
    return False


# --- QR start codes ------------------------------------------------------------------------


def _window(at: datetime) -> int:
    return int(at.timestamp() // CODE_WINDOW_SECONDS)


def _signature(trip: Trip, window: int) -> str:
    message = f"start:{trip.pk}:{trip.otp}:{window}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:20]


def start_code(trip: Trip, *, now: datetime | None = None) -> tuple[str, int]:
    """The QR payload for this moment and the seconds until it changes."""
    now = now or timezone.now()
    window = _window(now)
    expires_in = CODE_WINDOW_SECONDS - int(now.timestamp() % CODE_WINDOW_SECONDS)
    return f"RP1.{trip.pk}.{window}.{_signature(trip, window)}", expires_in


def start_code_valid(trip: Trip, code: str, *, now: datetime | None = None) -> bool:
    """Accepts this window's code and the previous one (a scan can straddle the boundary)."""
    now = now or timezone.now()
    try:
        version, trip_id, window, signature = code.strip().split(".")
        trip_id, window = int(trip_id), int(window)
    except ValueError:
        return False
    if version != "RP1" or trip_id != trip.pk or not 0 <= _window(now) - window <= 1:
        return False
    return hmac.compare_digest(signature, _signature(trip, window))


# --- Locations -------------------------------------------------------------------------------


def _rider_fix(trip: Trip, now: datetime) -> tuple[float, float] | None:
    if trip.rider_location_at is None or now - trip.rider_location_at > RIDER_FIX_FRESH:
        return None
    return trip.rider_lat, trip.rider_lng


def assert_together(trip: Trip, *, now: datetime) -> None:
    """Raise unless the driver is at the pickup and (when known) next to the rider's phone."""
    km = _driver_km_from_pickup(trip)
    if km is not None and km * 1000 > arrival_radius_meters():
        raise BusinessRuleViolation(f"You're {km * 1000:,.0f} m from the pickup point.")
    rider = _rider_fix(trip, now)
    driver = trip.driver
    if rider and driver and driver.current_lat is not None:
        apart = haversine_km(*rider, driver.current_lat, driver.current_lng)
        if apart > TOGETHER_KM:
            raise BusinessRuleViolation(
                f"Your rider's phone is {apart * 1000:,.0f} m away. Start the trip when you're "
                "together at the pickup."
            )


@dataclass(frozen=True)
class LocationResult:
    tracked: bool
    separated: bool = False


def record_rider_location(
    trip: Trip, *, user, lat: float, lng: float, now: datetime | None = None
) -> LocationResult:
    from .services import record_event

    now = now or timezone.now()
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider shares their location on a trip.")
    if trip.status not in (
        TripStatus.DRIVER_ASSIGNED,
        TripStatus.DRIVER_ARRIVED,
        TripStatus.IN_PROGRESS,
    ):
        return LocationResult(tracked=False)
    near_pickup = haversine_km(lat, lng, trip.pickup_lat, trip.pickup_lng) <= PLAUSIBLE_KM
    if trip.rider_location_at is None and not near_pickup:
        return LocationResult(tracked=False)  # a device that isn't really here: ignore it
    Trip.objects.filter(pk=trip.pk).update(rider_lat=lat, rider_lng=lng, rider_location_at=now)
    trip.rider_lat, trip.rider_lng, trip.rider_location_at = lat, lng, now

    driver = trip.driver
    if (
        trip.status == TripStatus.IN_PROGRESS
        and trip.separation_alerted_at is None
        and driver is not None
        and driver.current_lat is not None
        and haversine_km(lat, lng, driver.current_lat, driver.current_lng) > SEPARATION_KM
        # Claim the alert in the database: only one of several concurrent pings sends it.
        and Trip.objects.filter(pk=trip.pk, separation_alerted_at__isnull=True).update(
            separation_alerted_at=now
        )
    ):
        trip.separation_alerted_at = now
        record_event(
            trip,
            "SEPARATION",
            actor=user,
            message="Rider's phone and the car are over 1 km apart",
            at=now,
        )
        notify(
            trip.rider.user,
            "Are you in the car?",
            "Your phone and your driver's car are far apart. If something's wrong, tap SOS.",
            level=Level.WARNING,
            link=f"/ride/trips/{trip.pk}/",
        )
        notify(
            driver.user,
            "Is your rider with you?",
            "Their phone is over 1 km from your car. Contact support if they left the vehicle.",
            level=Level.WARNING,
            link="/drive",
        )
        return LocationResult(tracked=True, separated=True)
    return LocationResult(tracked=True)


# --- "Is this your car?" -------------------------------------------------------------------


def confirm_car(trip: Trip, *, user, is_my_car: bool, now: datetime | None = None) -> Trip:
    from apps.support.services import raise_sos

    from .services import record_event

    now = now or timezone.now()
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can confirm their car.")
    if trip.status not in (TripStatus.DRIVER_ASSIGNED, TripStatus.DRIVER_ARRIVED):
        raise InvalidStateTransition("You can confirm the car when it's arriving.")
    if is_my_car:
        if trip.car_confirmed_at is None:
            Trip.objects.filter(pk=trip.pk).update(car_confirmed_at=now)
            record_event(
                trip, "CAR_CONFIRMED", actor=user, message="Rider confirmed the car", at=now
            )
    else:
        raise_sos(
            trip=trip,
            user=user,
            lat=trip.rider_lat,
            lng=trip.rider_lng,
            note="Rider says the car at the pickup isn't the one shown in the app.",
            now=now,
        )
    trip.refresh_from_db()
    return trip
