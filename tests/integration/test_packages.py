"""Hourly rentals and intercity trips."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.payments.services import verify_ledger
from apps.pricing.models import RideType
from apps.rides import dispatch, packages
from apps.rides.models import TripStatus

from ..conftest import T_NAGAR, make_rider
from .helpers import pending_offer

pytestmark = pytest.mark.django_db

BENGALURU = (12.9716, 77.5946)
MAMALLAPURAM = (12.6208, 80.1945)  # ~50 km south of Chennai, outside the city area


def run(trip, driver, now, *, distance, minutes):
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    from apps.rides import services as rides

    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    drivers.update_location(driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now)
    return rides.complete_trip(
        trip, driver=driver, now=now + timedelta(minutes=minutes), actual_distance_km=distance
    )


def test_rental_quotes_and_overage(mini, make_driver, now, chennai):
    driver = make_driver(now=now)
    quote = packages.quotes(service="RENTAL", pickup=T_NAGAR, hours=2, at=now)
    by_code = {o["ride_type"].code: o for o in quote["options"]}
    assert set(by_code) == {"MINI", "SEDAN", "SUV"}
    assert by_code["MINI"]["pickup_eta_min"] is not None
    assert by_code["SUV"]["fare"].total > by_code["MINI"]["fare"].total
    assert {"hours": 2, "km": 20} in quote["packages"]
    with pytest.raises(BusinessRuleViolation, match="1, 2, 4 or 8"):
        packages.rental_fare(chennai, mini, 3)
    with pytest.raises(BusinessRuleViolation, match="cars"):
        packages.rental_fare(chennai, RideType.objects.get(code="BIKE"), 2)

    trip = packages.request_package_trip(
        rider=make_rider(),
        service="RENTAL",
        ride_type=mini,
        pickup=T_NAGAR,
        payment_method="UPI",
        hours=2,
        now=now,
    )
    assert trip.service == "RENTAL" and trip.package_km == 20
    assert (trip.dropoff_lat, trip.dropoff_lng) == (trip.pickup_lat, trip.pickup_lng)
    assert dispatch.offer_payload(pending_offer(trip))["package"] == {
        "kind": "RENTAL",
        "hours": 2,
        "km": 20,
    }
    quoted = trip.estimated_fare
    trip = run(trip, driver, now, distance=26, minutes=135)  # 6 km and 15 min over
    codes = {line.code for line in trip.final_fare.lines}
    assert {"PACKAGE", "EXTRA_KM", "EXTRA_TIME"} <= codes
    assert trip.fare_total > quoted
    assert verify_ledger()["balanced"]


def test_rental_within_package_costs_the_quote(mini, make_driver, now):
    driver = make_driver(now=now)
    trip = packages.request_package_trip(
        rider=make_rider(),
        service="RENTAL",
        ride_type=mini,
        pickup=T_NAGAR,
        payment_method="UPI",
        hours=1,
        now=now,
    )
    trip = run(trip, driver, now, distance=8, minutes=50)
    assert trip.status == TripStatus.COMPLETED and trip.fare_total == trip.estimated_fare


def test_intercity_one_way_and_round_trip(mini, make_driver, now, chennai):
    driver = make_driver(now=now)
    with pytest.raises(BusinessRuleViolation, match="normal ride"):
        packages.quotes(service="INTERCITY", pickup=T_NAGAR, dropoff=(13.06, 80.25), at=now)
    with pytest.raises(BusinessRuleViolation, match="up to 600"):
        packages.quotes(service="INTERCITY", pickup=T_NAGAR, dropoff=(19.07, 72.87), at=now)

    quote = packages.quotes(service="INTERCITY", pickup=T_NAGAR, dropoff=BENGALURU, at=now)
    assert 330 <= quote["distance_km"] <= 380
    mini_fare = next(o for o in quote["options"] if o["ride_type"].code == "MINI")["fare"]
    allowance = next(line for line in mini_fare.lines if line.code == "ALLOWANCE")
    assert allowance.amount == Decimal(300)
    assert mini_fare.driver_earning > allowance.amount

    short = packages.intercity_fare(chennai, mini, Decimal(55))
    assert "100 km" in short.lines[0].label  # one-way minimum
    two_days = packages.intercity_fare(chennai, mini, Decimal(55), round_trip=True, days=2)
    assert "500 km" in two_days.lines[0].label  # 250 km a day
    assert next(line for line in two_days.lines if line.code == "ALLOWANCE").amount == 600

    trip = packages.request_package_trip(
        rider=make_rider(),
        service="INTERCITY",
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MAMALLAPURAM,
        dropoff_address="Mamallapuram",
        payment_method="UPI",
        now=now,
    )
    payload = dispatch.offer_payload(pending_offer(trip))
    assert payload["package"]["kind"] == "INTERCITY" and payload["package"]["round_trip"] is False
    trip = run(trip, driver, now, distance=trip.estimated_distance_km, minutes=90)
    assert trip.fare_total == trip.estimated_fare
    assert verify_ledger()["balanced"]


def test_drivers_can_skip_intercity(mini, make_driver, now):
    driver = make_driver(now=now)
    driver.accepts_intercity = False
    driver.save()
    trip = packages.request_package_trip(
        rider=make_rider(),
        service="INTERCITY",
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MAMALLAPURAM,
        payment_method="UPI",
        now=now,
    )
    assert pending_offer(trip) is None


def test_api(api, make_driver, now):
    make_driver(now=now)
    client = api(make_rider().user)
    quote = client.post(
        "/api/v1/fares/packages/",
        {"service": "RENTAL", "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]}, "package_hours": 4},
        format="json",
    ).json()
    assert [o["ride_type"]["code"] for o in quote["options"]] == ["MINI", "SEDAN", "SUV"]
    trip = client.post(
        "/api/v1/trips/",
        {
            "service": "RENTAL",
            "ride_type": "MINI",
            "package_hours": 4,
            "payment_method": "UPI",
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1], "address": "T. Nagar"},
        },
        format="json",
    ).json()
    assert trip["service"] == "RENTAL" and trip["package_hours"] == 4 and trip["package_km"] == 40
    missing = client.post(
        "/api/v1/trips/",
        {
            "ride_type": "MINI",
            "payment_method": "UPI",
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
        },
        format="json",
    )
    assert missing.status_code == 400  # a normal ride needs a drop


def test_quotes_skip_car_types_paused_in_the_city(make_driver, now, chennai):
    from apps.pricing.models import FareRule

    make_driver(now=now)
    FareRule.objects.filter(city=chennai, ride_type__code="SUV").update(is_active=False)
    codes = [
        o["ride_type"].code
        for o in packages.quotes(service="RENTAL", pickup=T_NAGAR, hours=2, at=now)["options"]
    ]
    assert codes == ["MINI", "SEDAN"]
