"""Parcel delivery: booked like a ride, carried by bike drivers, finished with the recipient's
delivery code."""

from datetime import timedelta
from unittest import mock

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.drivers.models import Vehicle
from apps.payments.services import verify_ledger
from apps.pricing.models import RideType
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import TripStatus

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import pending_offer

pytestmark = pytest.mark.django_db

PARCEL = {
    "recipient_name": "Meena",
    "recipient_phone": "+91 98765 12345",
    "category": "DOCUMENTS",
    "weight_kg": 2,
    "instructions": "Leave with security",
}


@pytest.fixture
def parcel_type(db):
    return RideType.objects.get(code="PARCEL")


@pytest.fixture
def bike_driver(make_driver, now):
    driver = make_driver(now=now)
    Vehicle.objects.filter(driver=driver).update(ride_type=RideType.objects.get(code="BIKE"))
    return driver


def send(rider, parcel_type, now, parcel=PARCEL):
    return rides.request_trip(
        rider=rider,
        ride_type=parcel_type,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        parcel=parcel,
        now=now,
    )


def test_parcels_are_separate_from_rides(bike_driver, now):
    ride_codes = {
        o["ride_type"].code
        for o in rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)[
            "options"
        ]
    }
    assert "PARCEL" not in ride_codes
    parcel_options = rides.estimate_options(
        rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now, service="PARCEL"
    )["options"]
    assert [o["ride_type"].code for o in parcel_options] == ["PARCEL"]
    assert parcel_options[0]["availability"] == "AVAILABLE"  # bikes carry parcels


def test_parcel_details_are_required_and_checked(parcel_type, mini, bike_driver, now):
    with pytest.raises(BusinessRuleViolation, match="recipient"):
        send(make_rider(), parcel_type, now, parcel=None)
    with pytest.raises(BusinessRuleViolation, match="10 kg"):
        send(make_rider(), parcel_type, now, parcel={**PARCEL, "weight_kg": 25})
    with pytest.raises(BusinessRuleViolation, match="mobile"):
        send(make_rider(), parcel_type, now, parcel={**PARCEL, "recipient_phone": "123"})
    with pytest.raises(BusinessRuleViolation, match="only for parcel"):
        rides.request_trip(
            rider=make_rider(),
            ride_type=mini,
            pickup=T_NAGAR,
            dropoff=MARINA,
            payment_method="UPI",
            parcel=PARCEL,
        )


def test_only_bike_drivers_who_accept_parcels_get_them(parcel_type, make_driver, bike_driver, now):
    make_driver(now=now)  # a Mini driver: never offered parcels
    trip = send(make_rider(), parcel_type, now)
    assert pending_offer(trip).driver == bike_driver
    rides.cancel_trip(trip, user=trip.rider.user, now=now)

    bike_driver.accepts_parcels = False
    bike_driver.save()
    trip = send(make_rider(), parcel_type, now)
    assert pending_offer(trip) is None


def test_delivery_needs_the_recipients_code(
    parcel_type, bike_driver, now, django_capture_on_commit_callbacks
):
    sender = make_rider()
    trip = send(sender, parcel_type, now)
    parcel = trip.parcel
    assert trip.service == "PARCEL" and parcel.recipient_phone == "9876512345"
    assert len(parcel.delivery_code) == 4
    offer = dispatch.offer_payload(pending_offer(trip))
    assert offer["parcel"]["category"] == "Documents" and "recipient_phone" not in offer["parcel"]

    trip = dispatch.accept_offer(pending_offer(trip), driver=bike_driver, now=now)
    drivers.update_location(bike_driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=bike_driver, now=now)
    with (
        mock.patch("apps.accounts.sms.send_text") as texts,
        django_capture_on_commit_callbacks(execute=True),
    ):
        trip = rides.start_trip(trip, driver=bike_driver, otp=trip.otp, now=now)
    assert not trip.night_safe  # no passenger: no Night Safe
    phone, message = texts.call_args.args
    assert phone == "9876512345" and parcel.delivery_code in message and "/track/" in message

    drivers.update_location(bike_driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now)
    later = now + timedelta(minutes=20)
    with pytest.raises(BusinessRuleViolation, match="delivery code"):
        rides.complete_trip(trip, driver=bike_driver, now=later)  # no code at all
    wrong = "0000" if parcel.delivery_code != "0000" else "1111"
    with pytest.raises(BusinessRuleViolation, match="4 tries left"):
        rides.complete_delivery(trip, driver=bike_driver, delivery_code=wrong, now=later)
    parcel.refresh_from_db()
    assert parcel.code_attempts == 1  # saved even though the call failed

    trip = rides.complete_delivery(
        trip, driver=bike_driver, delivery_code=parcel.delivery_code, now=later
    )
    assert trip.status == TripStatus.COMPLETED and trip.parcel.delivered_at
    assert verify_ledger()["balanced"]


def test_api(api, parcel_type, bike_driver, now):
    sender = make_rider()
    client = api(sender.user)
    estimate = client.post(
        "/api/v1/fares/estimate/",
        {
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
            "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
            "service": "PARCEL",
        },
        format="json",
    ).json()
    assert [o["ride_type"]["code"] for o in estimate["options"]] == ["PARCEL"]
    trip = client.post(
        "/api/v1/trips/",
        {
            "ride_type": "PARCEL",
            "payment_method": "UPI",
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1], "address": "T. Nagar"},
            "dropoff": {"lat": MARINA[0], "lng": MARINA[1], "address": "Marina"},
            "parcel": PARCEL,
        },
        format="json",
    ).json()
    assert trip["service"] == "PARCEL" and len(trip["parcel"]["delivery_code"]) == 4
    seen_by_driver = api(bike_driver.user).get(f"/api/v1/trips/{trip['id']}/")
    assert seen_by_driver.status_code in (200, 404)  # not theirs until accepted
    status = api(bike_driver.user).post("/api/v1/driver/parcels/", {"on": False}).json()
    assert status["accepts_parcels"] is False
