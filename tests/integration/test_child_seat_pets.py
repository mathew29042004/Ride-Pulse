"""Child seat and pet rides go only to vehicles that have them; drivers set it for their car."""

import pytest

from apps.rides import services as rides
from apps.rides.models import RidePreference

from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db


def test_only_equipped_cars_get_the_trip(rider, mini, make_driver, now, api):
    plain = make_driver(now=now)
    equipped = make_driver(now=now, at=(13.0450, 80.2370))
    assert (
        api(equipped.user)
        .post(
            "/api/v1/driver/vehicle-options/",
            {"has_child_seat": True, "pet_friendly": True},
            format="json",
        )
        .json()["has_child_seat"]
    )
    trip = book(rider, mini, now=now, preferences=[RidePreference.CHILD_SEAT, RidePreference.PET])
    assert pending_offer(trip).driver == equipped  # the closer plain car is skipped
    assert plain


def test_bikes_drop_child_seats_and_pets(rider):
    from apps.pricing.models import RideType

    bike = RideType.objects.get(code="BIKE")
    assert rides.clean_preferences(["CHILD_SEAT", "PET", "QUIET"], bike) == ["QUIET"]


def test_autos_cant_claim_child_seats(make_driver, api):
    auto = make_driver(ride_type="AUTO", online=False)
    bad = api(auto.user).post(
        "/api/v1/driver/vehicle-options/", {"has_child_seat": True}, format="json"
    )
    assert bad.status_code == 422
    ok = api(auto.user).post(
        "/api/v1/driver/vehicle-options/", {"pet_friendly": True}, format="json"
    )
    assert ok.json()["pet_friendly"]
