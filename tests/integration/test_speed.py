"""Speed warnings: over the limit warns (rate-limited), school zones only on school hours,
speed worked out from positions when the phone doesn't send one."""

from datetime import datetime, time, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.drivers import services as drivers
from apps.drivers import speed
from apps.notifications.models import Notification

from ..conftest import T_NAGAR

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()


def school(chennai):
    return speed.SlowZone.objects.create(
        city=chennai,
        name="PSBB School",
        kind="SCHOOL",
        lat=T_NAGAR[0],
        lng=T_NAGAR[1],
        radius_m=300,
        limit_kmh=25,
    )


def weekday(h):
    d = timezone.localdate()
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return timezone.make_aware(datetime.combine(d, time(h)))


def test_school_zone_and_rate_limit(make_driver, chennai):
    zone = school(chennai)
    driver = make_driver(online=False)
    at = weekday(9)
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], speed_kmh=26, now=at)
    assert speed.SpeedAlert.objects.count() == 0  # within 10%
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], speed_kmh=40, now=at)
    alert = speed.SpeedAlert.objects.get()
    assert alert.zone == zone and alert.limit_kmh == 25
    assert Notification.objects.filter(
        user=driver.user, title__startswith="Slow down: school"
    ).exists()
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], speed_kmh=45, now=at)
    assert speed.SpeedAlert.objects.count() == 1  # warned once per 2 minutes
    cache.clear()
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], speed_kmh=45, now=weekday(20))
    assert speed.SpeedAlert.objects.count() == 1  # school zone not in force at 8 pm; 45 < 60


def test_speed_from_positions(make_driver, now):
    driver = make_driver(online=False)
    drivers.update_location(driver, lat=13.0000, lng=80.2500, now=now)
    # ~1.1 km in 30 s ≈ 133 km/h
    drivers.update_location(driver, lat=13.0100, lng=80.2500, now=now + timedelta(seconds=30))
    assert speed.SpeedAlert.objects.get().speed_kmh > 120
    assert speed.report(now=now + timedelta(minutes=1))["alerts"] == 1
