"""Monsoon / flood mode: surge held down, bikes paused in floods, flooded zones refused,
a banner for drivers in the city, and the alert ending by itself."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.geo.models import Zone
from apps.pricing import services as pricing
from apps.pricing.models import SurgeOverride
from apps.reliability import incidents, weather
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider

pytestmark = pytest.mark.django_db


@pytest.fixture
def zone(chennai):
    return Zone.objects.create(
        city=chennai,
        code="tn-test",
        name="T. Nagar test",
        center_lat=T_NAGAR[0],
        center_lng=T_NAGAR[1],
        radius_km=1.0,
    )


def test_rain_caps_surge_and_flood_removes_it(chennai, zone, ops, now):
    SurgeOverride.objects.create(
        zone=zone,
        multiplier=Decimal("1.9"),
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=12),
    )
    assert pricing.current_surge(zone, now=now) == Decimal("1.9")
    rain = weather.start(city=chennai, level="RAIN", user=ops, now=now)
    assert pricing.current_surge(zone, now=now) == Decimal("1.5")
    weather.end(rain, now=now)
    weather.start(city=chennai, level="FLOOD", user=ops, now=now)
    assert pricing.current_surge(zone, now=now) == Decimal(1)
    assert pricing.current_surge(zone, now=now + timedelta(hours=7)) == Decimal("1.9")  # ended


def test_flood_pauses_bikes_and_closes_flooded_zones(chennai, zone, ops, make_driver, now):
    driver = make_driver(now=now)
    weather.start(city=chennai, level="FLOOD", user=ops, zones=[zone], now=now)
    with pytest.raises(BusinessRuleViolation, match="flooded"):
        rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    away = (13.0827, 80.2707)  # Central, outside the flooded zone
    options = {
        o["ride_type"].code: o
        for o in rides.estimate_options(rider=None, pickup=away, dropoff=MARINA, at=now)["options"]
    }
    assert options["BIKE"]["availability"] == "CLOSED"
    assert "flooding" in options["BIKE"]["unavailable_reason"]
    from apps.pricing.models import RideType

    with pytest.raises(BusinessRuleViolation, match="paused"):
        rides.request_trip(
            rider=make_rider(),
            ride_type=RideType.objects.get(code="BIKE"),
            pickup=away,
            dropoff=MARINA,
            payment_method="UPI",
            now=now,
        )
    banner = incidents.banner_for(driver.user)
    assert banner["severity"] == "MAJOR" and "T. Nagar test" in banner["message"]


def test_ops_api(api, ops, chennai, zone):
    client = api(ops)
    made = client.post(
        "/api/v1/ops/weather/", {"city": chennai.pk, "level": "RAIN", "hours": 3}, format="json"
    )
    assert made.status_code == 201 and made.json()["active"]
    listed = client.get("/api/v1/ops/weather/").json()
    assert listed["alerts"][0]["id"] == made.json()["id"] and listed["cities"]
    ended = client.post(f"/api/v1/ops/weather/{made.json()['id']}/end/").json()
    assert not ended["active"]
