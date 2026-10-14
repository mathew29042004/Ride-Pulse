"""Ride types nobody can take right now: closed hours, no drivers nearby, suggestions, boost."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.pricing.models import RideType
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider

pytestmark = pytest.mark.django_db


def options_by_code(result):
    return {o["ride_type"].code: o for o in result["options"]}


def closed_now(ride_type, now):
    """Service hours that exclude the current local hour."""
    hour = timezone.localtime(now).hour
    ride_type.service_start_hour, ride_type.service_end_hour = (hour + 1) % 24, (hour + 2) % 24
    ride_type.save()


def test_closed_and_missing_ride_types_suggest_an_alternative(make_driver, now):
    make_driver(now=now)  # a Mini driver at T. Nagar
    bike = RideType.objects.get(code="BIKE")
    closed_now(bike, now)
    options = options_by_code(
        rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    )
    assert options["MINI"]["availability"] == "AVAILABLE" and options["MINI"]["suggestion"] is None
    assert options["BIKE"]["availability"] == "CLOSED"
    assert options["BIKE"]["pickup_eta_min"] is None
    assert "Bike rides run" in options["BIKE"]["unavailable_reason"]
    assert options["SUV"]["availability"] == "NONE"
    for code in ("BIKE", "AUTO", "SUV"):
        assert options[code]["suggestion"]["ride_type"] == "MINI"  # the only one available

    with pytest.raises(BusinessRuleViolation, match="Bike rides run"):
        rides.request_trip(
            rider=make_rider(), ride_type=bike, pickup=T_NAGAR, dropoff=MARINA, payment_method="UPI"
        )


def test_no_suggestion_when_nothing_is_available(now):
    options = options_by_code(
        rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    )
    assert all(o["availability"] == "NONE" and o["suggestion"] is None for o in options.values())


def test_bike_hours_wrap_past_midnight(now):
    bike = RideType(code="X", service_start_hour=22, service_end_hour=6)
    late = timezone.localtime(now).replace(hour=23)
    assert bike.is_open(late) and bike.is_open(late + timedelta(hours=3))
    assert not bike.is_open(late.replace(hour=12))
    assert RideType(service_start_hour=5, service_end_hour=23).service_hours_label == "5 am – 11 pm"


def test_book_with_a_search_boost(mini, now):
    trip = rides.request_trip(
        rider=make_rider(),
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        boost=20,
        now=now,
    )
    assert trip.boost_amount == Decimal(20) and trip.boosted_at == now
    assert any(line.kind == "BOOST" for line in trip.estimate.lines)
    with pytest.raises(BusinessRuleViolation):
        rides.request_trip(
            rider=make_rider(),
            ride_type=mini,
            pickup=T_NAGAR,
            dropoff=MARINA,
            payment_method="UPI",
            boost=15,
        )


def test_estimate_api_shows_availability(api, rider, make_driver, now):
    make_driver(now=now)
    body = (
        api(rider.user)
        .post(
            "/api/v1/fares/estimate/",
            {
                "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
                "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
            },
            format="json",
        )
        .json()
    )
    bike = next(o for o in body["options"] if o["ride_type"]["code"] == "BIKE")
    assert bike["availability"] == "NONE" and bike["suggestion"]["ride_type"] == "MINI"


def test_suggestions_prefer_enough_seats(make_driver, now):
    from apps.drivers.models import Vehicle

    mini_driver = make_driver(now=now)
    bike_driver = make_driver(now=now)
    Vehicle.objects.filter(driver=bike_driver).update(ride_type=RideType.objects.get(code="BIKE"))
    options = options_by_code(
        rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    )
    assert options["SUV"]["suggestion"]["ride_type"] == "MINI"  # 4 seats beat a cheaper bike
    assert options["AUTO"]["suggestion"]["ride_type"] == "MINI"  # 3 seats: the bike is too small
    assert mini_driver.pk != bike_driver.pk
