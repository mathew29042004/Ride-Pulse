"""Shared rides: two riders going the same way share one Mini."""

from datetime import timedelta

import pytest

from apps.drivers import services as drivers
from apps.drivers.models import Availability
from apps.pricing.models import RideType
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.pooling import driver_run

from ..conftest import ADYAR, MARINA, T_NAGAR, make_rider
from .helpers import book, money, pending_offer

pytestmark = pytest.mark.django_db

NEAR_T_NAGAR = (13.0450, 80.2370)  # ~500 m away
NEAR_MARINA = (13.0520, 80.2790)


@pytest.fixture
def share(db):
    return RideType.objects.get(code="SHARE")


def first_rider_assigned(share, make_driver, now):
    driver = make_driver(now=now)
    trip = book(make_rider(), share, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    return trip, driver


def test_share_is_cheaper_than_mini(share, mini, make_driver, now):
    make_driver(now=now)
    result = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    fares = {o["ride_type"].code: o["estimate"].fare.total for o in result["options"]}
    assert money(fares["SHARE"]) < money(fares["MINI"]) * money("0.8")


def test_second_rider_joins_and_driver_serves_both(share, make_driver, now):
    first, driver = first_rider_assigned(share, make_driver, now)
    later = now + timedelta(minutes=1)
    second = book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=NEAR_MARINA, now=later)
    assert second.status == "DRIVER_ASSIGNED" and second.driver == driver
    first.refresh_from_db()
    assert first.pool_id == second.pool_id == first.trip_number
    assert not second.offers.exists()  # joined directly, no dispatch

    # Pickups first (in order), then drop-offs.
    assert list(driver_run(driver.pk)) == [first, second]
    t = later + timedelta(minutes=3)
    for trip in (first, second):
        drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=t)
        rides.mark_arrived(trip, driver=driver, now=t)
        rides.start_trip(trip, driver=driver, otp=trip.otp, now=t + timedelta(minutes=1))
        t += timedelta(minutes=3)
    assert [x.status for x in driver_run(driver.pk)] == ["IN_PROGRESS", "IN_PROGRESS"]

    end = t + timedelta(minutes=20)
    drivers.update_location(driver, lat=first.dropoff_lat, lng=first.dropoff_lng, now=end)
    rides.complete_trip(
        first, driver=driver, now=end, actual_distance_km=first.estimated_distance_km
    )
    driver.refresh_from_db()
    assert driver.availability == Availability.ON_TRIP  # still carrying the co-rider
    second.refresh_from_db()
    rides.complete_trip(
        second, driver=driver, now=end, actual_distance_km=second.estimated_distance_km
    )
    driver.refresh_from_db()
    assert driver.availability == Availability.ONLINE


def test_no_match_when_going_elsewhere_or_full(share, make_driver, now):
    _first, driver = first_rider_assigned(share, make_driver, now)
    opposite = book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=ADYAR, now=now)
    assert opposite.status == "REQUESTED" and not opposite.pool_id
    second = book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=NEAR_MARINA, now=now)
    assert second.driver == driver
    third = book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=NEAR_MARINA, now=now)
    assert third.driver != driver  # a Share car takes two riders at most


def test_co_rider_cancelling_keeps_the_driver_busy(share, make_driver, now):
    first, driver = first_rider_assigned(share, make_driver, now)
    second = book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=NEAR_MARINA, now=now)
    rides.cancel_trip(second, user=second.rider.user, now=now + timedelta(seconds=30))
    driver.refresh_from_db()
    assert driver.availability == Availability.ON_TRIP
    rides.cancel_trip(first, user=first.rider.user, now=now + timedelta(seconds=40))
    driver.refresh_from_db()
    assert driver.availability == Availability.ONLINE


def test_api_shows_co_riders(api, share, make_driver, now):
    first, driver = first_rider_assigned(share, make_driver, now)
    book(make_rider(), share, pickup=NEAR_T_NAGAR, dropoff=NEAR_MARINA, now=now)
    data = api(first.rider.user).get(f"/api/v1/trips/{first.pk}/").json()
    assert data["co_riders"] == 1 and data["pool_id"] == first.trip_number
    active = api(driver.user).get("/api/v1/trips/active/").json()
    assert active["id"] == first.pk
