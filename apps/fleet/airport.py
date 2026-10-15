"""Airport queue: drivers waiting at the airport get its pickups in the order they arrived.

* A free, online driver inside an airport zone joins that airport's queue automatically (from
  their location updates). Stepping outside for more than ``AIRPORT_QUEUE_GRACE_MINUTES`` (to
  grab tea, or to give up) drops them out; coming back is a fresh spot at the end.
* Dispatch offers an airport pickup to the queue first (the longest-waiting driver who fits),
  and only then to drivers driving past.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F
from django.utils import timezone

from apps.drivers.models import Availability, DriverProfile
from apps.geo.distance import haversine_km
from apps.geo.models import Zone

from .models import AirportQueueEntry, QueueStatus

# Rank bonus (in minutes of ETA) for the queue: enough to beat any passing driver, and ordered
# by position so the first in line wins.
QUEUE_BONUS_MINUTES = 60.0


def _airports() -> list[tuple[int, int, float, float, float]]:
    zones = cache.get("fleet:airports")
    if zones is None:
        zones = list(
            Zone.objects.filter(is_airport=True).values_list(
                "pk", "city_id", "center_lat", "center_lng", "radius_km"
            )
        )
        cache.set("fleet:airports", zones, 600)
    return zones


def airport_at(city_id: int, lat: float, lng: float) -> int | None:
    for pk, zone_city, zlat, zlng, radius in _airports():
        if zone_city == city_id and haversine_km(lat, lng, zlat, zlng) <= radius:
            return pk
    return None


def on_location(driver: DriverProfile, lat: float, lng: float, now: datetime) -> None:
    """Called with every location update of a driver who isn't on a trip."""
    if not _airports():
        return
    waiting = AirportQueueEntry.objects.filter(driver=driver, status=QueueStatus.WAITING).first()
    zone = (
        airport_at(driver.city_id, lat, lng) if driver.availability == Availability.ONLINE else None
    )
    if waiting:
        if zone == waiting.zone_id:
            if waiting.outside_since:
                AirportQueueEntry.objects.filter(pk=waiting.pk).update(outside_since=None)
            return
        if driver.availability != Availability.ONLINE:
            _leave(waiting, now)
            return
        if waiting.outside_since is None:
            AirportQueueEntry.objects.filter(pk=waiting.pk).update(outside_since=now)
        elif now - waiting.outside_since > timedelta(
            minutes=settings.RIDE_PULSE["AIRPORT_QUEUE_GRACE_MINUTES"]
        ):
            _leave(waiting, now)
        return
    if zone is not None:
        try:
            with transaction.atomic():
                AirportQueueEntry.objects.create(zone_id=zone, driver=driver, joined_at=now)
        except IntegrityError:
            pass  # a concurrent update already queued them


def _leave(entry: AirportQueueEntry, now: datetime) -> None:
    AirportQueueEntry.objects.filter(pk=entry.pk).update(status=QueueStatus.LEFT, ended_at=now)


def leave_on_offline(driver: DriverProfile, now: datetime | None = None) -> None:
    AirportQueueEntry.objects.filter(driver=driver, status=QueueStatus.WAITING).update(
        status=QueueStatus.LEFT, ended_at=now or timezone.now()
    )


def positions(zone_id: int) -> dict[int, int]:
    """driver id -> place in line (1 = next)."""
    ids = AirportQueueEntry.objects.filter(zone_id=zone_id, status=QueueStatus.WAITING).values_list(
        "driver_id", flat=True
    )
    return {driver_id: n for n, driver_id in enumerate(ids, start=1)}


def queue_bonus(trip, driver_id: int, cache_: dict) -> float:
    """Minutes taken off a candidate's rank score for an airport pickup."""
    zone = trip.pickup_zone
    if zone is None or not zone.is_airport:
        return 0.0
    if zone.pk not in cache_:
        cache_[zone.pk] = positions(zone.pk)
    place = cache_[zone.pk].get(driver_id)
    if place is None:
        return 0.0
    return QUEUE_BONUS_MINUTES - min(place, 50) * 0.5


def on_assigned(trip, driver: DriverProfile, now: datetime) -> None:
    """The driver got a trip: their spot is used (only an airport pickup counts as served)."""
    AirportQueueEntry.objects.filter(driver=driver, status=QueueStatus.WAITING).update(
        status=QueueStatus.DISPATCHED
        if trip.pickup_zone_id and trip.pickup_zone.is_airport
        else QueueStatus.LEFT,
        ended_at=now,
        trip=trip,
    )


def my_spot(driver: DriverProfile) -> dict | None:
    entry = (
        AirportQueueEntry.objects.filter(driver=driver, status=QueueStatus.WAITING)
        .select_related("zone")
        .first()
    )
    if entry is None:
        return None
    line = positions(entry.zone_id)
    return {
        "airport": entry.zone.name,
        "position": line.get(driver.pk),
        "waiting": len(line),
        "joined_at": entry.joined_at.isoformat(),
        "outside": entry.outside_since is not None,
    }


def overview(*, now: datetime | None = None) -> list[dict]:
    """Ops: every airport's line right now and the last 24 hours."""
    now = now or timezone.now()
    since = now - timedelta(hours=24)
    zones = Zone.objects.filter(is_airport=True).select_related("city").order_by("city__name")
    waiting = dict(
        AirportQueueEntry.objects.filter(status=QueueStatus.WAITING)
        .values_list("zone_id")
        .annotate(n=Count("pk"))
        .values_list("zone_id", "n")
    )
    served = {
        row["zone_id"]: row
        for row in AirportQueueEntry.objects.filter(
            status=QueueStatus.DISPATCHED, ended_at__gte=since
        )
        .values("zone_id")
        .annotate(n=Count("pk"), wait=Avg(F("ended_at") - F("joined_at")))
    }
    from apps.rides.models import Trip

    pickups = dict(
        Trip.objects.filter(pickup_zone__is_airport=True, requested_at__gte=since)
        .values_list("pickup_zone")
        .annotate(n=Count("pk"))
        .values_list("pickup_zone", "n")
    )
    rows = []
    for zone in zones:
        stats = served.get(zone.pk, {})
        wait = stats.get("wait")
        rows.append(
            {
                "zone_id": zone.pk,
                "airport": zone.name,
                "city": zone.city.name,
                "waiting": waiting.get(zone.pk, 0),
                "served_24h": stats.get("n", 0),
                "pickups_24h": pickups.get(zone.pk, 0),
                "avg_wait_minutes": round(wait.total_seconds() / 60) if wait else None,
            }
        )
    return rows
