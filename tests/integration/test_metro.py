"""Metro first and last mile: plans only when cheaper on longer trips; booking books the first
ride and schedules the last; "at the station" sends it now."""

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.rides import metro
from apps.rides.models import ScheduledRide

from ..conftest import MARINA, T_NAGAR
from .helpers import drive_to_completion

pytestmark = pytest.mark.django_db
AIRPORT_SIDE = (12.9830, 80.1700)  # near Chennai Airport station
NORTH = (13.1080, 80.2830)  # near Washermanpet


def test_plan_long_trip(chennai, mini, now):
    p = metro.plan(city=chennai, pickup=AIRPORT_SIDE, dropoff=NORTH, ride_type=mini, at=now)
    assert p and p["entry"]["name"] == "Chennai Airport" and p["exit"]["name"] == "Washermanpet"
    assert p["total"] < p["direct_fare"] and p["saves"] > 0 and p["metro_fare"] > 0
    assert (
        metro.plan(city=chennai, pickup=T_NAGAR, dropoff=MARINA, ride_type=mini, at=now) is None
    )  # too short


def test_book_and_arrive(api, rider, mini, make_driver, now):
    make_driver(now=now, at=AIRPORT_SIDE)
    made = api(rider.user).post(
        "/api/v1/scheduled-rides/metro-book/",
        {
            "ride_type": "MINI",
            "pickup": {"lat": AIRPORT_SIDE[0], "lng": AIRPORT_SIDE[1]},
            "dropoff": {"lat": NORTH[0], "lng": NORTH[1], "address": "Home"},
            "payment_method": "UPI",
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    last = ScheduledRide.objects.get(pk=made.json()["last_mile"]["id"])
    assert last.metro_trip_id == made.json()["trip_id"] and last.status == "SCHEDULED"
    with pytest.raises(BusinessRuleViolation, match="hasn't finished"):
        metro.at_station(last)
    from apps.rides.models import Trip

    drive_to_completion(Trip.objects.get(pk=made.json()["trip_id"]), now=now)
    make_driver(now=now, at=NORTH)
    sent = api(rider.user).post(f"/api/v1/scheduled-rides/{last.pk}/at-station/").json()
    assert sent["status"] == "DISPATCHED", sent["failure_reason"]
    with pytest.raises(BusinessRuleViolation):
        metro.at_station(ScheduledRide.objects.get(pk=last.pk))


def test_not_offered_outside_metro_cities(mini, now):
    from apps.geo.models import City

    salem = City.objects.get(slug="salem")
    assert (
        metro.plan(
            city=salem,
            pickup=(salem.center_lat, salem.center_lng),
            dropoff=(salem.center_lat + 0.1, salem.center_lng),
            ride_type=mini,
            at=now,
        )
        is None
    )
