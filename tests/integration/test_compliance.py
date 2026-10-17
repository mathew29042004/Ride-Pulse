"""India's Aggregator Guidelines: per-state surge and cancellation caps are enforced, drivers need
police verification and induction to go online, and the dashboard finds what to fix."""

from datetime import date
from decimal import Decimal

import pytest

from apps.compliance import checks, rules
from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.drivers.models import DriverProfile, Vehicle
from apps.geo.models import Zone
from apps.pricing.models import SurgeOverride
from apps.pricing.services import current_surge

from ..conftest import T_NAGAR

pytestmark = pytest.mark.django_db


def test_surge_never_exceeds_the_state_cap_even_with_an_override(chennai, now, settings):
    from datetime import timedelta

    zone = Zone.objects.filter(city=chennai).first()
    SurgeOverride.objects.create(
        zone=zone,
        multiplier=Decimal("3.0"),
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
        reason="Concert",
    )
    assert current_surge(zone, now=now) == Decimal("2.0")
    settings.AGGREGATOR_RULES = {"Tamil Nadu": {"surge_cap": "1.5"}}
    assert current_surge(zone, now=now) == Decimal("1.5")


def test_cancellation_fee_is_capped_by_share_and_amount():
    assert rules.cap_cancellation_fee(Decimal(75), Decimal(300), "Kerala") == Decimal("30.00")
    assert rules.cap_cancellation_fee(Decimal(500), Decimal(5000), "Kerala") == Decimal("100.00")
    assert rules.cap_cancellation_fee(Decimal(20), Decimal(900), "Kerala") == Decimal("20.00")


def test_unverified_driver_cannot_go_online_and_shows_on_the_dashboard(make_driver, now):
    driver = make_driver(now=now, online=False)
    DriverProfile.objects.filter(pk=driver.pk).update(police_verified_on=None)
    Vehicle.objects.filter(driver=driver).update(year=2015)
    with pytest.raises(BusinessRuleViolation, match="Police verification"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    report = checks.state_report("Tamil Nadu")
    status = {c["key"]: c["status"] for c in report["checks"]}
    assert status["police_verification"] != "OK" and status["vehicle_age"] != "OK"
    assert [d["id"] for d in report["unverified"]] == [driver.pk]
    checks.record_police_verification(driver, reference="TNPV-1234", user=None, on=date.today())
    drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
