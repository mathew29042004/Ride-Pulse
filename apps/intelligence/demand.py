"""Demand prediction: how many trips each zone will see in the next hour, and where drivers
are short.

The model is deliberately simple and explainable (a seasonal baseline with a live correction):

1. **Seasonal baseline:** trips requested in the zone in the same hour on the same weekday over
   the past four weeks, weighted towards recent weeks (40/30/20/10).
2. **Live correction:** how the last hour compares with what the baseline expected for it
   (clipped to 0.5-2x), so a rainy evening or a concert lifts the forecast straight away.

Forecast = baseline for next hour x correction. Comparing it with the drivers free near the
zone gives a shortage score; drivers nearby are nudged towards the worst zones (at most once
every 45 minutes). ``backtest`` measures accuracy on the past day of real data.

The forecast blends this seasonal view (40%) with persistence (60%): the last hour per zone,
nudged by the usual change from this hour to the next. Persistence copes with sudden shifts
the four-week history hasn't seen yet.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay
from django.utils import timezone

from apps.drivers.models import Availability, DriverProfile, OnboardingStatus
from apps.geo.distance import haversine_km
from apps.geo.models import Zone
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.rides.models import Trip

from .models import DemandNudge

WEEK_WEIGHTS = (0.4, 0.3, 0.2, 0.1)
TRIPS_PER_DRIVER_HOUR = 2.0
NUDGE_EVERY = timedelta(minutes=45)
NUDGE_RADIUS_KM = 6.0
MIN_FORECAST = 4
SEASONAL_WEIGHT = 0.4


def _hour_start(at: datetime) -> datetime:
    return timezone.localtime(at).replace(minute=0, second=0, microsecond=0)


def _counts_by_zone(start: datetime, end: datetime, city_id: int | None) -> dict[int, int]:
    trips = Trip.objects.filter(
        requested_at__gte=start, requested_at__lt=end, pickup_zone__isnull=False
    )
    if city_id:
        trips = trips.filter(city_id=city_id)
    return dict(
        trips.values_list("pickup_zone").annotate(n=Count("pk")).values_list("pickup_zone", "n")
    )


def _baseline(hour: datetime, city_id: int | None) -> dict[int, float]:
    """Weighted trips per zone in this hour-of-week over the last four weeks."""
    totals: dict[int, float] = defaultdict(float)
    weight_seen = 0.0
    for weeks_back, weight in enumerate(WEEK_WEIGHTS, start=1):
        start = hour - timedelta(weeks=weeks_back)
        counts = _counts_by_zone(start, start + timedelta(hours=1), city_id)
        if not counts:
            continue
        weight_seen += weight
        for zone, n in counts.items():
            totals[zone] += weight * n
    if not weight_seen:
        return {}
    return {zone: value / weight_seen for zone, value in totals.items()}


def _base_predict(*, city_id: int | None = None, now: datetime | None = None) -> dict[int, float]:
    """Expected trips per zone in the hour starting at the next full hour."""
    now = now or timezone.now()
    next_hour = _hour_start(now) + timedelta(hours=1)
    baseline_next = _baseline(next_hour, city_id)
    last_start = now - timedelta(hours=1)
    baseline_last = _baseline(_hour_start(last_start), city_id)
    last_hour = _counts_by_zone(last_start, now, city_id)
    expected_last, actual_last = sum(baseline_last.values()), sum(last_hour.values())
    if actual_last == 0:
        return baseline_next
    # 1. Seasonal: the usual next hour, scaled by how busy the last hour was (clipped).
    ratio = min(2.0, max(0.5, actual_last / expected_last)) if expected_last >= 5 else 1.0
    seasonal = {zone: value * ratio for zone, value in baseline_next.items()}
    # 2. Persistence: the last hour per zone, following the usual hour-to-hour shape.
    shape = sum(baseline_next.values()) / expected_last if expected_last >= 5 else 1.0
    persistence = {zone: n * min(1.5, max(0.67, shape)) for zone, n in last_hour.items()}
    zones = set(seasonal) | set(persistence)
    return {
        z: SEASONAL_WEIGHT * seasonal.get(z, 0) + (1 - SEASONAL_WEIGHT) * persistence.get(z, 0)
        for z in zones
    }


def predict(
    *, city_id: int | None = None, now: datetime | None = None, with_context: bool = True
) -> dict[int, float]:
    """The forecast, lifted by rain (per city) and by events near each zone."""
    now = now or timezone.now()
    base = _base_predict(city_id=city_id, now=now)
    if not with_context:
        return base
    from . import context

    next_hour = _hour_start(now) + timedelta(hours=1)
    zones = {z.pk: z for z in Zone.objects.filter(pk__in=base)}
    event_zones = Zone.objects.filter(
        city_id__in=context.events_in_window(
            next_hour, next_hour + timedelta(hours=1), city_id=city_id
        ).values("city_id")
    )
    for zone in event_zones:
        zones.setdefault(zone.pk, zone)
    factors: dict[int, float] = {}
    result = {}
    for pk, zone in zones.items():
        if zone.city_id not in factors:
            factors[zone.city_id] = context.weather_factor(
                context.current_weather(zone.city_id, now=now)
            )
        extra, _ = context.event_extra_trips(zone, next_hour)
        value = base.get(pk, 0.0) * factors[zone.city_id] + extra
        if value > 0:
            result[pk] = value
    return result


def _free_drivers(city_id: int | None):
    drivers = DriverProfile.objects.filter(
        availability=Availability.ONLINE,
        onboarding_status=OnboardingStatus.APPROVED,
        current_lat__isnull=False,
    )
    if city_id:
        drivers = drivers.filter(city_id=city_id)
    return list(drivers.values("pk", "user_id", "current_lat", "current_lng", "city_id"))


def forecast(*, city_id: int | None = None, now: datetime | None = None, limit: int = 30) -> dict:
    """Zones ranked by expected shortage in the next hour."""
    now = now or timezone.now()
    expected = predict(city_id=city_id, now=now)
    zones = Zone.objects.filter(pk__in=expected).select_related("city")
    drivers = _free_drivers(city_id)
    rows = []
    from . import context

    next_hour = _hour_start(now) + timedelta(hours=1)
    for zone in zones:
        trips = expected[zone.pk]
        near = sum(
            1
            for d in drivers
            if d["city_id"] == zone.city_id
            and haversine_km(d["current_lat"], d["current_lng"], zone.center_lat, zone.center_lng)
            <= zone.radius_km + 1
        )
        capacity = near * TRIPS_PER_DRIVER_HOUR
        shortage = trips / capacity if capacity else (trips if trips >= 1 else 0)
        rows.append(
            {
                "zone_id": zone.pk,
                "zone": zone.name,
                "city": zone.city.name,
                "lat": zone.center_lat,
                "lng": zone.center_lng,
                "expected_trips": round(trips, 1),
                "drivers_nearby": near,
                "shortage": round(shortage, 2),
                "status": "SHORT" if shortage >= 1.5 else "TIGHT" if shortage >= 1 else "OK",
                "reasons": context.event_extra_trips(zone, next_hour)[1],
            }
        )
    rows.sort(key=lambda r: (-r["shortage"], -r["expected_trips"]))
    next_hour = _hour_start(now) + timedelta(hours=1)
    return {
        "for_hour": next_hour.isoformat(),
        "total_expected": round(sum(r["expected_trips"] for r in rows)),
        "zones": rows[:limit],
    }


def nudge_drivers(*, now: datetime | None = None, max_zones: int = 10) -> int:
    """Tell free drivers near the worst-short zones where demand is about to rise."""
    now = now or timezone.now()
    short = [
        z
        for z in forecast(now=now, limit=200)["zones"]
        if z["status"] == "SHORT" and z["expected_trips"] >= MIN_FORECAST
    ][:max_zones]
    if not short:
        return 0
    recent = set(
        DemandNudge.objects.filter(created_at__gte=now - NUDGE_EVERY).values_list(
            "driver_id", flat=True
        )
    )
    drivers = [d for d in _free_drivers(None) if d["pk"] not in recent]
    sent = 0
    for zone in short:
        for d in drivers:
            distance = haversine_km(d["current_lat"], d["current_lng"], zone["lat"], zone["lng"])
            if d["pk"] in recent or not 1.5 <= distance <= NUDGE_RADIUS_KM:
                continue
            DemandNudge.objects.create(
                driver_id=d["pk"],
                zone_id=zone["zone_id"],
                expected_trips=round(zone["expected_trips"]),
                created_at=now,
            )
            notify(
                _user(d["user_id"]),
                f"Busy soon: {zone['zone']}",
                f"About {round(zone['expected_trips'])} trips expected there in the next hour, "
                f"{distance:.1f} km from you.",
                level=Level.INFO,
                link="/drive",
            )
            recent.add(d["pk"])
            sent += 1
    return sent


def _user(user_id: int):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(pk=user_id)


def hot_zones_for(driver: DriverProfile, *, now: datetime | None = None, limit: int = 3) -> list:
    """For the driver app: the busiest zones near this driver in the next hour."""
    if driver.current_lat is None:
        return []
    rows = forecast(city_id=driver.city_id, now=now, limit=100)["zones"]
    for row in rows:
        row["distance_km"] = round(
            haversine_km(driver.current_lat, driver.current_lng, row["lat"], row["lng"]), 1
        )
    near = [r for r in rows if r["distance_km"] <= 10 and r["expected_trips"] >= 2]
    near.sort(key=lambda r: (-r["shortage"], r["distance_km"]))
    return near[:limit]


def backtest(*, hours: int = 24, now: datetime | None = None, city_id: int | None = None) -> dict:
    """Forecast each of the past ``hours`` hours using only earlier data and compare the total
    with what really happened (for one city, or the whole platform).

    Reported as accuracy (100% minus the weighted absolute percentage error) for the model, for
    the history-only seasonal baseline, and for the naive guess "same as last hour", so it's
    clear whether the model earns its keep. Only "steady" hours count: within 3x of the hour
    before. Bigger jumps (in the demo, the simulator being switched on or off) can't be
    forecast from history by any method. Per-zone counts are too small at this data volume for
    a meaningful hourly accuracy figure, so zones are ranked rather than scored.
    """
    now = now or timezone.now()
    end = _hour_start(now)
    errors = {"model": 0.0, "seasonal": 0.0, "naive": 0.0}
    trips = tested = 0
    for back in range(hours, 0, -1):
        hour = end - timedelta(hours=back)
        actual = sum(_counts_by_zone(hour, hour + timedelta(hours=1), city_id).values())
        before = sum(_counts_by_zone(hour - timedelta(hours=1), hour, city_id).values())
        if not actual or not before or not 1 / 3 <= actual / before <= 3:
            continue
        guesses = {
            "model": sum(predict(city_id=city_id, now=hour - timedelta(minutes=1)).values()),
            "seasonal": sum(_baseline(hour, city_id).values()),
            "naive": before,
        }
        for name, guess in guesses.items():
            errors[name] += abs(guess - actual)
        trips += actual
        tested += 1
    if not trips:
        return {"hours": 0, "trips": 0, "model": None, "seasonal": None, "naive": None}
    accuracy = {name: max(0.0, round(100 - 100 * err / trips, 1)) for name, err in errors.items()}
    return {"hours": tested, "trips": trips, **accuracy}


def demand_profile(*, city_id: int | None = None, days: int = 28) -> list[dict]:
    """Average trips by weekday and hour (the seasonality the forecast leans on)."""
    since = timezone.now() - timedelta(days=days)
    trips = Trip.objects.filter(requested_at__gte=since)
    if city_id:
        trips = trips.filter(city_id=city_id)
    rows = (
        trips.annotate(dow=ExtractIsoWeekDay("requested_at"), hour=ExtractHour("requested_at"))
        .values("dow", "hour")
        .annotate(n=Count("pk"))
    )
    weeks = max(1, days / 7)
    return [{"dow": r["dow"], "hour": r["hour"], "avg": round(r["n"] / weeks, 1)} for r in rows]
