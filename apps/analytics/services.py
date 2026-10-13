"""Operational analytics. Aggregations run in PostgreSQL; nothing is computed row by row."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import connection
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import ExtractHour, Left
from django.utils import timezone

from apps.drivers.models import Availability, DriverProfile, DriverSession
from apps.geo import geohash
from apps.rides.models import ACTIVE_STATUSES, CancelledBy, Trip, TripStatus
from apps.support.models import OPEN_TICKET_STATUSES, IncidentStatus, SafetyIncident, SupportTicket

ZERO = Decimal("0.00")


def _trips(*, since: datetime, until: datetime, city=None):
    trips = Trip.objects.filter(requested_at__gte=since, requested_at__lt=until)
    return trips.filter(city=city) if city else trips


def _minutes(value: timedelta | None) -> float | None:
    return round(value.total_seconds() / 60, 1) if value else None


def overview(*, since: datetime, until: datetime, city=None) -> dict:
    completed = Q(status=TripStatus.COMPLETED)
    agg = _trips(since=since, until=until, city=city).aggregate(
        requested=Count("id"),
        completed=Count("id", filter=completed),
        cancelled_by_rider=Count(
            "id", filter=Q(status=TripStatus.CANCELLED, cancelled_by=CancelledBy.RIDER)
        ),
        cancelled_other=Count(
            "id", filter=Q(status=TripStatus.CANCELLED) & ~Q(cancelled_by=CancelledBy.RIDER)
        ),
        no_driver=Count("id", filter=Q(status=TripStatus.NO_DRIVER_FOUND)),
        gmv=Sum("fare_total", filter=completed, default=ZERO),
        gst=Sum("gst_amount", filter=completed, default=ZERO),
        driver_earnings=Sum("driver_earning", filter=completed, default=ZERO),
        commission=Sum("platform_commission", filter=completed, default=ZERO),
        discounts=Sum("discount_amount", filter=completed, default=ZERO),
        tips=Sum("tip_amount", filter=completed, default=ZERO),
        avg_fare=Avg("fare_total", filter=completed),
        avg_distance=Avg("actual_distance_km", filter=completed),
        avg_surge=Avg("surge_multiplier"),
        avg_wait=Avg(
            ExpressionWrapper(F("assigned_at") - F("requested_at"), output_field=DurationField()),
            filter=Q(assigned_at__isnull=False),
        ),
        avg_pickup=Avg(
            ExpressionWrapper(F("arrived_at") - F("assigned_at"), output_field=DurationField()),
            filter=Q(arrived_at__isnull=False),
        ),
    )
    requested = agg["requested"] or 0
    return {
        "requested": requested,
        "completed": agg["completed"],
        "completion_rate": round(100 * agg["completed"] / requested, 1) if requested else None,
        "cancelled_by_rider": agg["cancelled_by_rider"],
        "cancelled_other": agg["cancelled_other"],
        "no_driver_found": agg["no_driver"],
        "gmv": agg["gmv"],
        # What the platform keeps: everything except GST and the drivers' share.
        "net_revenue": agg["gmv"] - agg["gst"] - agg["driver_earnings"],
        "commission": agg["commission"],
        "driver_earnings": agg["driver_earnings"],
        "discounts": agg["discounts"],
        "tips": agg["tips"],
        "avg_fare": round(agg["avg_fare"], 2) if agg["avg_fare"] else None,
        "avg_distance_km": round(agg["avg_distance"], 2) if agg["avg_distance"] else None,
        "avg_surge": round(agg["avg_surge"], 2) if agg["avg_surge"] else None,
        "avg_wait_min": _minutes(agg["avg_wait"]),
        "avg_pickup_min": _minutes(agg["avg_pickup"]),
    }


def live_status(*, city=None) -> dict:
    drivers = DriverProfile.objects.all()
    trips = Trip.objects.filter(status__in=ACTIVE_STATUSES)
    if city:
        drivers, trips = drivers.filter(city=city), trips.filter(city=city)
    counts = drivers.aggregate(
        online=Count("id", filter=Q(availability=Availability.ONLINE)),
        on_trip=Count("id", filter=Q(availability=Availability.ON_TRIP)),
    )
    busy = counts["online"] + counts["on_trip"]
    return {
        "drivers_online": counts["online"],
        "drivers_on_trip": counts["on_trip"],
        "utilisation": round(100 * counts["on_trip"] / busy, 1) if busy else None,
        "active_trips": trips.count(),
        "searching": trips.filter(status=TripStatus.REQUESTED).count(),
        "open_sos": SafetyIncident.objects.exclude(status=IncidentStatus.RESOLVED).count(),
        "open_tickets": SupportTicket.objects.filter(status__in=OPEN_TICKET_STATUSES).count(),
    }


_SERIES_SQL = """
WITH buckets AS (
    SELECT generate_series(
        date_trunc(%(unit)s, %(since)s::timestamptz AT TIME ZONE %(tz)s),
        date_trunc(%(unit)s, %(until)s::timestamptz AT TIME ZONE %(tz)s - interval '1 second'),
        %(step)s::interval
    ) AS bucket
)
SELECT b.bucket,
       COUNT(t.id) AS requested,
       COUNT(t.id) FILTER (WHERE t.status = 'COMPLETED') AS completed,
       COUNT(t.id) FILTER (WHERE t.status IN ('CANCELLED', 'NO_DRIVER_FOUND')) AS lost,
       COALESCE(SUM(t.fare_total) FILTER (WHERE t.status = 'COMPLETED'), 0) AS gmv,
       COALESCE(AVG(t.surge_multiplier), 1) AS avg_surge
FROM buckets b
LEFT JOIN {table} t
       ON date_trunc(%(unit)s, t.requested_at AT TIME ZONE %(tz)s) = b.bucket
      AND t.requested_at >= %(since)s AND t.requested_at < %(until)s
      AND (%(city)s::bigint IS NULL OR t.city_id = %(city)s::bigint)
GROUP BY b.bucket
ORDER BY b.bucket
"""


def time_series(*, since: datetime, until: datetime, unit: str = "day", city=None) -> list[dict]:
    """Trips and GMV per hour or day; generate_series() fills buckets that had no trips."""
    if unit not in ("hour", "day"):
        raise ValueError("unit must be 'hour' or 'day'")
    params = {
        "unit": unit,
        "step": f"1 {unit}",
        "since": since,
        "until": until,
        "tz": settings.TIME_ZONE,
        "city": city.pk if city else None,
    }
    with connection.cursor() as cursor:
        cursor.execute(_SERIES_SQL.format(table=Trip._meta.db_table), params)
        rows = cursor.fetchall()
    return [
        {
            "bucket": bucket.isoformat(),
            "requested": requested,
            "completed": completed,
            "lost": lost,
            "gmv": gmv,
            "avg_surge": round(float(avg_surge), 2),
        }
        for bucket, requested, completed, lost, gmv, avg_surge in rows
    ]


def demand_heatmap(
    *, since: datetime, until: datetime, city=None, precision: int = 6
) -> list[dict]:
    """Ride requests per geohash cell (~1.2 × 0.6 km at precision 6)."""
    cells = (
        _trips(since=since, until=until, city=city)
        .annotate(cell=Left("pickup_geohash", precision))
        .values("cell")
        .annotate(requests=Count("id"))
        .order_by("-requests")[:400]
    )
    result = []
    for row in cells:
        lat, lng, _, _ = geohash.decode(row["cell"])
        result.append(
            {
                "cell": row["cell"],
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "requests": row["requests"],
            }
        )
    return result


def zone_performance(*, since: datetime, until: datetime, city=None) -> list[dict]:
    rows = (
        _trips(since=since, until=until, city=city)
        .filter(pickup_zone__isnull=False)
        .values("pickup_zone__name", "pickup_zone__city__name")
        .annotate(
            requests=Count("id"),
            completed=Count("id", filter=Q(status=TripStatus.COMPLETED)),
            avg_surge=Avg("surge_multiplier"),
            gmv=Sum("fare_total", filter=Q(status=TripStatus.COMPLETED), default=ZERO),
            avg_wait=Avg(
                ExpressionWrapper(
                    F("assigned_at") - F("requested_at"), output_field=DurationField()
                ),
                filter=Q(assigned_at__isnull=False),
            ),
        )
        .order_by("-requests")
    )
    return [
        {
            "zone": r["pickup_zone__name"],
            "city": r["pickup_zone__city__name"],
            "requests": r["requests"],
            "completed": r["completed"],
            "fulfilment": round(100 * r["completed"] / r["requests"], 1) if r["requests"] else None,
            "avg_surge": round(r["avg_surge"], 2) if r["avg_surge"] else 1,
            "gmv": r["gmv"],
            "avg_wait_min": _minutes(r["avg_wait"]),
        }
        for r in rows
    ]


def ride_type_mix(*, since: datetime, until: datetime, city=None) -> list[dict]:
    rows = (
        _trips(since=since, until=until, city=city)
        .filter(status=TripStatus.COMPLETED)
        .values("ride_type__code", "ride_type__name")
        .annotate(
            trips=Count("id"), gmv=Sum("fare_total", default=ZERO), avg_fare=Avg("fare_total")
        )
        .order_by("-trips")
    )
    return [
        {
            "code": r["ride_type__code"],
            "name": r["ride_type__name"],
            "trips": r["trips"],
            "gmv": r["gmv"],
            "avg_fare": round(r["avg_fare"], 2) if r["avg_fare"] else None,
        }
        for r in rows
    ]


def hourly_demand(*, since: datetime, until: datetime, city=None) -> list[dict]:
    counts = dict(
        _trips(since=since, until=until, city=city)
        .annotate(hour=ExtractHour("requested_at", tzinfo=timezone.get_current_timezone()))
        .values_list("hour")
        .annotate(n=Count("id"))
    )
    return [{"hour": h, "requests": counts.get(h, 0)} for h in range(24)]


def driver_leaderboard(
    *, since: datetime, until: datetime, city=None, limit: int = 10
) -> list[dict]:
    rows = (
        _trips(since=since, until=until, city=city)
        .filter(status=TripStatus.COMPLETED)
        .values(
            "driver_id",
            "driver__user__first_name",
            "driver__user__last_name",
            "driver__rating",
            "driver__safety_score",
        )
        .annotate(
            trips=Count("id"),
            earnings=Sum("driver_earning", default=ZERO),
            tips=Sum("tip_amount", default=ZERO),
        )
        .order_by("-earnings")[:limit]
    )
    return [
        {
            "driver_id": r["driver_id"],
            "name": f"{r['driver__user__first_name']} {r['driver__user__last_name']}".strip(),
            "trips": r["trips"],
            "earnings": r["earnings"] + r["tips"],
            "rating": r["driver__rating"],
            "safety_score": r["driver__safety_score"],
        }
        for r in rows
    ]


def hours_online(*, since: datetime, until: datetime, city=None) -> float:
    """Total driver-hours online in the window (sessions clipped to the window)."""
    sessions = DriverSession.objects.filter(started_at__lt=until).filter(
        Q(ended_at__isnull=True) | Q(ended_at__gt=since)
    )
    if city:
        sessions = sessions.filter(driver__city=city)
    now = timezone.now()
    seconds = 0.0
    for start, end in sessions.values_list("started_at", "ended_at"):
        seconds += max(0.0, (min(end or now, until) - max(start, since)).total_seconds())
    return round(seconds / 3600, 1)
