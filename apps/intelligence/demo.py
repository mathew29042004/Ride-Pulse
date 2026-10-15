"""Demo scenarios: plant a few fraud patterns in recent completed trips and write the first
briefing, so the intelligence pages have something to show on a fresh database."""

import random
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.notifications import services as notifications
from apps.rides.models import Trip, TripFlag, TripStatus

from . import briefing, fraud
from .models import FraudCase


def _recent_drivers(rng: random.Random, min_trips: int, exclude: set[int]) -> list[int]:
    since = timezone.now() - timedelta(days=10)
    rows = (
        Trip.objects.filter(status=TripStatus.COMPLETED, completed_at__gte=since)
        .exclude(driver_id__in=exclude)
        .values("driver_id")
        .annotate(n=Count("pk"))
        .filter(n__gte=min_trips)
    )
    ids = [r["driver_id"] for r in rows]
    rng.shuffle(ids)
    return ids


def _trips(driver_id: int, n: int):
    since = timezone.now() - timedelta(days=10)
    return list(
        Trip.objects.filter(
            driver_id=driver_id, status=TripStatus.COMPLETED, completed_at__gte=since
        )
        .order_by("-completed_at")
        .values_list("pk", flat=True)[:n]
    )


def _flag(trip_ids: list[int], flag: str) -> None:
    for trip in Trip.objects.filter(pk__in=trip_ids):
        if flag not in trip.flags:
            Trip.objects.filter(pk=trip.pk).update(flags=[*trip.flags, flag])


def seed(*, seed: int = 5, log=print) -> dict:
    if FraudCase.objects.exists():
        return {"fraud_cases": 0}
    rng = random.Random(seed)
    used: set[int] = set()
    drivers = _recent_drivers(rng, 4, used)
    if len(drivers) < 4:
        return {"fraud_cases": 0}
    log("Planting a few fraud patterns for the review queue…")
    spoofers, padder, colluder = drivers[:2], drivers[2], drivers[3]
    for driver_id in spoofers:
        _flag(_trips(driver_id, rng.choice([2, 3, 4])), TripFlag.GPS_JUMP)
    _flag(_trips(padder, 4), TripFlag.ROUTE_DEVIATION)
    pair = _trips(colluder, 4)
    rider_id = Trip.objects.get(pk=pair[0]).rider_id
    Trip.objects.filter(pk__in=pair).update(rider_id=rider_id)
    with notifications.muted():
        found = fraud.scan()
        briefing.generate(send=False)
    log(f"  {found['opened']} fraud cases, briefing for yesterday written")
    return {"fraud_cases": found["opened"]}
