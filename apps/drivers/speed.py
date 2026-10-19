"""Live speed warnings and slow zones.

* Every location update carries the phone's speed (or it's worked out from the last position).
* The limit is the city default for the vehicle, or a slow zone's limit while inside it: schools
  (25 km/h on weekdays 7 am – 6 pm), hospitals and markets (30 km/h, always).
* More than 10% over the limit warns the driver at once (at most every 2 minutes) and records a
  speed alert on the trip; the safety team sees repeat offenders. Riders are never shown alerts.
"""

from datetime import timedelta

from django.core.cache import cache
from django.db import models
from django.utils import timezone

from apps.core.models import LatitudeField, LongitudeField
from apps.geo.distance import haversine_km

DEFAULT_LIMIT = {"BIKE": 50, "AUTO": 45}  # km/h in town; cars use CITY_LIMIT
CITY_LIMIT = 60
TOLERANCE = 1.10
WARN_EVERY = timedelta(minutes=2)


class ZoneKind(models.TextChoices):
    SCHOOL = "SCHOOL", "School"
    HOSPITAL = "HOSPITAL", "Hospital"
    MARKET = "MARKET", "Market"


class SlowZone(models.Model):
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="slow_zones")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=ZoneKind.choices)
    lat = LatitudeField()
    lng = LongitudeField()
    radius_m = models.PositiveSmallIntegerField(default=250)
    limit_kmh = models.PositiveSmallIntegerField(default=25)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "drivers"
        ordering = ["city__name", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.limit_kmh} km/h)"

    def in_force(self, when) -> bool:
        if self.kind != ZoneKind.SCHOOL:
            return True
        local = timezone.localtime(when)
        return local.weekday() < 5 and 7 <= local.hour < 18


class SpeedAlert(models.Model):
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="speed_alerts"
    )
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    zone = models.ForeignKey(
        SlowZone, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    speed_kmh = models.PositiveSmallIntegerField()
    limit_kmh = models.PositiveSmallIntegerField()
    lat = LatitudeField()
    lng = LongitudeField()
    at = models.DateTimeField(db_index=True)

    class Meta:
        app_label = "drivers"
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"{self.driver_id} {self.speed_kmh}/{self.limit_kmh}"


def limit_at(driver, lat: float, lng: float, now) -> tuple[int, SlowZone | None]:
    vehicle = (
        driver.vehicles.filter(is_active=True).select_related("ride_type").first()
        if hasattr(driver, "vehicles")
        else None
    )
    code = vehicle.ride_type.served_by.code if vehicle else ""
    base = DEFAULT_LIMIT.get(code, CITY_LIMIT)
    # Location updates are the hot path: each city's zones are cached for 5 minutes.
    city_zones = cache.get_or_set(
        f"slow-zones:{driver.city_id}",
        lambda: list(SlowZone.objects.filter(city_id=driver.city_id, is_active=True)),
        300,
    )
    zones = [
        z
        for z in city_zones
        if haversine_km(z.lat, z.lng, lat, lng) * 1000 <= z.radius_m and z.in_force(now)
    ]
    if zones:
        zone = min(zones, key=lambda z: z.limit_kmh)
        return min(base, zone.limit_kmh), zone
    return base, None


def check(driver, *, lat, lng, speed_kmh, prev, now, trip_id) -> SpeedAlert | None:
    """Called on every location update. ``prev`` is (lat, lng, at) before this update."""
    if speed_kmh is None and prev and prev[0] is not None and prev[2]:
        seconds = (now - prev[2]).total_seconds()
        if 2 <= seconds <= 60:
            speed_kmh = haversine_km(prev[0], prev[1], lat, lng) / seconds * 3600
    if not speed_kmh or speed_kmh < 20:
        return None
    limit, zone = limit_at(driver, lat, lng, now)
    if speed_kmh <= limit * TOLERANCE:
        return None
    if SpeedAlert.objects.filter(driver=driver, at__gt=now - WARN_EVERY, at__lte=now).exists():
        return None  # warned in the last 2 minutes
    alert = SpeedAlert.objects.create(
        driver=driver,
        trip_id=trip_id,
        zone=zone,
        speed_kmh=round(speed_kmh),
        limit_kmh=limit,
        lat=lat,
        lng=lng,
        at=now,
    )
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    where = f"{zone.get_kind_display().lower()} zone, " if zone else ""
    notify(
        driver.user,
        f"Slow down: {where}limit {limit} km/h",
        f"You were doing {round(speed_kmh)} km/h. Safer driving keeps your safety score "
        "and your riders' trust.",
        level=Level.WARNING,
        link="/drive",
    )
    return alert


def report(*, days: int = 7, now=None) -> dict:
    from django.db.models import Count

    now = now or timezone.now()
    rows = SpeedAlert.objects.filter(at__gte=now - timedelta(days=days))
    top = (
        rows.values(
            "driver_id", "driver__user__first_name", "driver__user__last_name", "driver__city__name"
        )
        .annotate(n=Count("id"))
        .order_by("-n")[:15]
    )
    zones = (
        rows.exclude(zone=None)
        .values("zone__name", "zone__kind")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )
    return {
        "days": days,
        "alerts": rows.count(),
        "in_slow_zones": rows.exclude(zone=None).count(),
        "drivers": rows.values("driver").distinct().count(),
        "top_drivers": [
            {
                "driver_id": r["driver_id"],
                "name": f"{r['driver__user__first_name']} {r['driver__user__last_name']}",
                "city": r["driver__city__name"],
                "alerts": r["n"],
            }
            for r in top
        ],
        "top_zones": [
            {"name": z["zone__name"], "kind": z["zone__kind"], "alerts": z["n"]} for z in zones
        ],
        "zones": SlowZone.objects.filter(is_active=True).count(),
    }


def seed_demo(*, seed: int = 101, log=print) -> dict:
    """Slow zones near neighbourhood centres in every city (schools, hospitals, markets), and a
    week of speed alerts for some drivers."""
    import random

    from apps.geo.models import Zone

    from .models import DriverProfile

    if SlowZone.objects.exists():
        return {"slow_zones": 0}
    rng = random.Random(seed)
    zones = []
    for z in Zone.objects.filter(is_airport=False).select_related("city"):
        for kind, limit, label in rng.sample(
            [
                ("SCHOOL", 25, "Government Higher Secondary School"),
                ("HOSPITAL", 30, "General Hospital"),
                ("MARKET", 30, "Market"),
            ],
            2,
        ):
            zones.append(
                SlowZone(
                    city=z.city,
                    name=f"{z.name} {label}",
                    kind=kind,
                    limit_kmh=limit,
                    lat=z.center_lat + rng.uniform(-0.006, 0.006),
                    lng=z.center_lng + rng.uniform(-0.006, 0.006),
                    radius_m=rng.choice([200, 250, 300]),
                )
            )
    SlowZone.objects.bulk_create(zones)
    now = timezone.now()
    alerts = []
    for d in DriverProfile.objects.exclude(current_lat=None).order_by("?")[:60]:
        for _ in range(rng.choice([1, 1, 2, 4, 7])):
            zone = rng.choice(zones) if rng.random() < 0.4 else None
            limit = zone.limit_kmh if zone else 60
            alerts.append(
                SpeedAlert(
                    driver=d,
                    zone=zone,
                    speed_kmh=limit + rng.randint(8, 35),
                    limit_kmh=limit,
                    lat=d.current_lat,
                    lng=d.current_lng,
                    at=now - timedelta(hours=rng.uniform(1, 160)),
                )
            )
    SpeedAlert.objects.bulk_create(alerts)
    log(f"  slow zones: {len(zones)}, speed alerts: {len(alerts)}")
    return {"slow_zones": len(zones), "speed_alerts": len(alerts)}
