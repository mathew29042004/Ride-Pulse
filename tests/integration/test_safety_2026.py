"""Safety features from Uber's 2026 India launch: own Ride PIN, ambulance SOS, no typing while
driving, and seatbelt/helmet reminders."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.notifications.models import Notification
from apps.rides import dispatch
from apps.rides import services as rides
from apps.support.services import raise_sos

from ..conftest import make_rider
from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db


def assigned(mini, make_driver, now, rider=None):
    driver = make_driver(now=now)
    trip = book(rider or make_rider(), mini, now=now)
    return dispatch.accept_offer(pending_offer(trip), driver=driver, now=now), driver


def test_own_ride_pin(api, mini, make_driver, now):
    rider = make_rider()
    client = api(rider.user)
    assert client.patch("/api/v1/rider/me/", {"ride_pin": "12a4"}).status_code == 400
    assert client.patch("/api/v1/rider/me/", {"ride_pin": "1111"}).status_code == 400
    assert client.patch("/api/v1/rider/me/", {"ride_pin": "4826"}).status_code == 200
    rider.refresh_from_db()
    trip, _ = assigned(mini, make_driver, now, rider)
    assert trip.otp == "4826"


def test_ambulance_sos_alerts_ops(mini, make_driver, now, ops):
    trip, _ = assigned(mini, make_driver, now)
    incident = raise_sos(trip=trip, user=trip.rider.user, ambulance=True, now=now)
    assert incident.ambulance_requested
    assert Notification.objects.filter(title__contains="AMBULANCE NEEDED").exists()


def test_driver_cannot_type_while_moving(mini, make_driver, now):
    trip, driver = assigned(mini, make_driver, now)
    t = timezone.now()
    drivers.update_location(driver, lat=13.04, lng=80.24, speed_kmh=35, now=t)
    with pytest.raises(BusinessRuleViolation, match="Don't type and drive"):
        rides.send_message(trip, user=driver.user, body="where are you exactly")
    rides.send_message(trip, user=driver.user, body="I'm on my way")  # quick reply is fine
    rides.send_message(trip, user=trip.rider.user, body="At the gate")  # riders aren't limited
    drivers.update_location(driver, lat=13.04, lng=80.24, speed_kmh=0, now=t + timedelta(seconds=5))
    rides.send_message(trip, user=driver.user, body="where are you exactly")


def test_seatbelt_reminder_on_start(mini, make_driver, now):
    trip, driver = assigned(mini, make_driver, now)
    at = now + timedelta(minutes=3)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=at)
    rides.mark_arrived(trip, driver=driver, now=at)
    rides.start_trip(trip, driver=driver, otp=trip.otp, now=at + timedelta(minutes=1))
    assert Notification.objects.filter(user=trip.rider.user, title="Buckle up").exists()
