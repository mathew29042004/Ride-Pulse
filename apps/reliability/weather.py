"""Monsoon / flood mode. Ops turn it on for a city when the IMD warns of heavy rain or roads flood.

* Heavy rain: surge is held to at most 1.5x (no gouging when people most need a ride).
* Flooding: no surge at all, bike taxis are paused (unsafe on waterlogged roads), and pick-ups
  or drops inside flooded zones are refused with a clear message.
* Riders and drivers in the city see the alert as a banner; drivers get a safety notice.
The alert ends by itself at ``ends_at``.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

from .models import WeatherAlert, WeatherLevel

SURGE_CAP = {WeatherLevel.RAIN: Decimal("1.5"), WeatherLevel.FLOOD: Decimal(1)}
PAUSED_IN_FLOOD = {"BIKE"}  # vehicle codes


def active(city, *, now: datetime | None = None) -> WeatherAlert | None:
    if city is None:
        return None
    now = now or timezone.now()
    alerts = WeatherAlert.objects.filter(city=city, starts_at__lte=now, ends_at__gt=now)
    # A flood beats rain if both are on.
    return alerts.filter(level=WeatherLevel.FLOOD).first() or alerts.first()


def surge_cap(city, *, now=None) -> Decimal | None:
    alert = active(city, now=now)
    return SURGE_CAP[alert.level] if alert else None


def paused_vehicle(city, vehicle_code: str, *, now=None) -> bool:
    alert = active(city, now=now)
    return bool(alert and alert.level == WeatherLevel.FLOOD and vehicle_code in PAUSED_IN_FLOOD)


def check_points(city, points, *, now=None) -> None:
    """Refuse a trip that starts, stops or ends in a flooded zone."""
    alert = active(city, now=now)
    if not alert or alert.level != WeatherLevel.FLOOD:
        return
    for zone in alert.zones.all():
        for lat, lng in points:
            if zone.distance_km(lat, lng) <= zone.radius_km:
                raise BusinessRuleViolation(
                    f"{zone.name} is flooded right now, so we can't pick up or drop there. "
                    "Choose a point on higher ground nearby.",
                    field="pickup",
                )


def start(*, city, level: str, user, hours: int = 6, zones=(), message: str = "", now=None):
    now = now or timezone.now()
    if level == WeatherLevel.FLOOD and not message:
        message = "Flooding in parts of the city. Bike taxis are paused and fares have no surge."
    elif not message:
        message = "Heavy rain: rides may take longer. Surge is capped at 1.5x."
    alert = WeatherAlert.objects.create(
        city=city,
        level=level,
        message=message[:240],
        starts_at=now,
        ends_at=now + timedelta(hours=max(1, min(int(hours), 72))),
        created_by=user,
    )
    alert.zones.set([z for z in zones if z.city_id == city.pk])
    _tell_drivers(alert)
    return alert


def end(alert: WeatherAlert, *, now=None) -> WeatherAlert:
    alert.ends_at = min(alert.ends_at, now or timezone.now())
    alert.save(update_fields=["ends_at"])
    return alert


def _tell_drivers(alert: WeatherAlert) -> None:
    from apps.drivers.models import DriverProfile
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    zones = ", ".join(z.name for z in alert.zones.all())
    body = alert.message + (f" Avoid: {zones}." if zones else "")
    body += " Never drive through water you can't see the road under."
    for driver in DriverProfile.objects.filter(city=alert.city).select_related("user")[:2000]:
        notify(driver.user, alert.get_level_display(), body, level=Level.WARNING, link="/drive")


def banner(city, *, now=None) -> dict | None:
    alert = active(city, now=now)
    if not alert:
        return None
    return {
        "number": f"WX-{alert.pk}",
        "severity": "MAJOR" if alert.level == WeatherLevel.FLOOD else "MINOR",
        "message": alert.message
        + (
            f" Flooded: {', '.join(z.name for z in alert.zones.all())}."
            if alert.zones.exists()
            else ""
        ),
        "status": alert.get_level_display(),
    }


def row(alert: WeatherAlert, *, now=None) -> dict:
    now = now or timezone.now()
    return {
        "id": alert.pk,
        "city": alert.city.name,
        "level": alert.level,
        "level_label": alert.get_level_display(),
        "zones": [z.name for z in alert.zones.all()],
        "message": alert.message,
        "starts_at": alert.starts_at,
        "ends_at": alert.ends_at,
        "active": alert.starts_at <= now < alert.ends_at,
        "by": alert.created_by.get_full_name() if alert.created_by_id else None,
    }
