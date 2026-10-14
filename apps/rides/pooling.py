"""Shared rides (like Uber Pool / Ola Share): two riders going the same way share one Mini.

A Share request is first matched against Share trips that already have a driver on the way to
their pickup. A match needs pickups close together and drop-offs in the same direction, so the
detour stays small. The new rider joins that driver's run (pickup A, pickup B, drop A, drop B);
otherwise the request is dispatched like any other, and can itself pick up a co-rider later.

Riders pay the lower Share fare whether or not a co-rider turns up.
"""

from datetime import datetime

from django.db.models import Case, IntegerField, Value, When

from apps.geo.distance import bearing_degrees, haversine_km
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import ACTIVE_DRIVER_STATUSES, Trip, TripStatus

SHARE_CODE = "SHARE"
MAX_RIDERS = 2
PICKUP_RADIUS_KM = 1.5
MAX_HEADING_GAP = 40  # degrees between the two trips' directions
MAX_DETOUR = 1.5  # the joining trip may be at most this much longer than the first one
JOINABLE = (TripStatus.DRIVER_ASSIGNED, TripStatus.DRIVER_ARRIVED)


def is_share(trip: Trip) -> bool:
    return trip.ride_type.code == SHARE_CODE


def _heading(trip: Trip) -> float:
    return bearing_degrees(trip.pickup_lat, trip.pickup_lng, trip.dropoff_lat, trip.dropoff_lng)


def compatible(first: Trip, joining: Trip) -> bool:
    if first.rider_id == joining.rider_id or first.city_id != joining.city_id:
        return False
    if (
        haversine_km(first.pickup_lat, first.pickup_lng, joining.pickup_lat, joining.pickup_lng)
        > PICKUP_RADIUS_KM
    ):
        return False
    gap = abs(_heading(first) - _heading(joining)) % 360
    if min(gap, 360 - gap) > MAX_HEADING_GAP:
        return False
    first_km = float(first.estimated_distance_km or 0)
    return float(joining.estimated_distance_km or 0) <= max(first_km, 1.0) * MAX_DETOUR


def try_match(trip: Trip, *, now: datetime) -> Trip | None:
    """Join a waiting Share run if one fits. Call inside the request's transaction."""
    from .services import _change_status, record_event

    if not is_share(trip) or trip.stop_lat is not None:
        return None
    candidates = (
        Trip.objects.select_for_update(of=("self",))
        .select_related("driver__user", "vehicle", "rider__user")
        .filter(ride_type=trip.ride_type, city=trip.city, status__in=JOINABLE)
        .exclude(rider=trip.rider)
        .order_by("assigned_at")
    )
    for first in candidates:
        run = Trip.objects.filter(driver=first.driver, status__in=ACTIVE_DRIVER_STATUSES)
        if run.count() >= MAX_RIDERS or not compatible(first, trip):
            continue
        pool_id = first.pool_id or first.trip_number
        if not first.pool_id:
            Trip.objects.filter(pk=first.pk).update(pool_id=pool_id)
        driver = first.driver
        trip = _change_status(
            trip,
            TripStatus.DRIVER_ASSIGNED,
            actor=driver.user,
            at=now,
            message=f"Sharing {driver.name}'s ride with another rider",
            driver=driver,
            vehicle=first.vehicle,
            assigned_at=now,
            pickup_eta_min=first.pickup_eta_min,
            pool_id=pool_id,
        )
        record_event(first, "POOL_MATCHED", message="A co-rider joined this shared ride", at=now)
        notify(
            trip.rider.user,
            f"{driver.name} is on the way",
            f"You're sharing with one co-rider · Ride PIN {trip.otp}",
            level=Level.SUCCESS,
            link=f"/ride/trips/{trip.pk}/",
        )
        notify(
            first.rider.user,
            "A co-rider is joining you",
            "Your driver will make one extra pickup on the way.",
            link=f"/ride/trips/{first.pk}/",
        )
        notify(
            driver.user,
            f"New co-rider: {trip.rider.user.first_name or 'Rider'}",
            f"Pick up at {trip.pickup_address or 'the pin'} · PIN on their app",
            level=Level.SUCCESS,
        )
        from apps.realtime import broadcast

        broadcast.driver_event(driver.pk, "pool_joined", {"trip_id": trip.pk})
        return trip
    return None


def driver_run(driver_id: int):
    """A driver's active trips in the order to serve them: pickups first, then drop-offs."""
    return (
        Trip.objects.filter(driver_id=driver_id, status__in=ACTIVE_DRIVER_STATUSES)
        .annotate(
            leg=Case(
                When(status__in=JOINABLE, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("leg", "assigned_at", "pk")
    )


def co_riders(trip: Trip) -> int:
    if not trip.pool_id:
        return 0
    return (
        Trip.objects.filter(pool_id=trip.pool_id, status__in=ACTIVE_DRIVER_STATUSES)
        .exclude(pk=trip.pk)
        .count()
    )
