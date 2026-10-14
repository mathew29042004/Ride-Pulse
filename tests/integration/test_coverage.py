"""City service catalogue: ride types nobody in a city can drive are paused automatically."""

import pytest

from apps.drivers import services as drivers
from apps.drivers.models import Vehicle
from apps.pricing import coverage
from apps.pricing.models import FareRule, RideType
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR

pytestmark = pytest.mark.django_db


def active_codes(city):
    return set(
        FareRule.objects.filter(city=city, is_active=True).values_list("ride_type__code", flat=True)
    )


def test_ride_types_follow_driver_coverage(
    chennai, make_driver, ops, django_capture_on_commit_callbacks
):
    driver = make_driver()  # a Mini driver
    changes = coverage.sync(city_id=chennai.pk)
    assert "Chennai · Prime SUV" in changes["paused"]
    assert active_codes(chennai) == {"MINI"}
    options = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA)["options"]
    assert [o["ride_type"].code for o in options] == ["MINI"]

    # An ops manager switched SUV off by hand: coverage never turns it back on.
    FareRule.objects.filter(city=chennai, ride_type__code="SEDAN").update(auto_paused=False)

    # A bike driver joins: Bike (and Parcel, carried by bikes) come back.
    bike = make_driver()
    Vehicle.objects.filter(driver=bike).update(ride_type=RideType.objects.get(code="BIKE"))
    changes = coverage.sync(city_id=chennai.pk)
    assert {"Chennai · Bike", "Chennai · Parcel"} <= set(changes["resumed"])
    assert active_codes(chennai) == {"MINI", "BIKE", "PARCEL"}

    # Suspending the only Mini driver pauses Mini (on commit).
    with django_capture_on_commit_callbacks(execute=True):
        drivers.suspend_driver(driver, reason="Investigation", actor=ops)
    assert "MINI" not in active_codes(chennai)
    assert driver.pk
