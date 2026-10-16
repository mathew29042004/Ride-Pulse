"""The trip watchdog closes trips that stopped moving, and never charges the rider for them."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.drivers import services as drivers
from apps.drivers.models import DriverProfile
from apps.payments.services import verify_ledger
from apps.reliability import watchdog
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import Trip, TripFlag, TripStatus
from apps.support.models import SupportTicket

from ..conftest import make_rider
from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db


def _silence(driver, minutes):
    DriverProfile.objects.filter(pk=driver.pk).update(
        location_updated_at=timezone.now() - timedelta(minutes=minutes)
    )


def test_abandoned_mid_ride_is_closed_free_with_a_ticket(mini, make_driver, now, admin):
    driver = make_driver(now=now)
    trip = book(make_rider(), mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    # Still within the expected time, or the driver still sending: left alone.
    assert watchdog.sweep(now=now + timedelta(minutes=20))["abandoned"] == 0
    Trip.objects.filter(pk=trip.pk).update(started_at=timezone.now() - timedelta(hours=5))
    _silence(driver, 60)
    assert watchdog.sweep()["abandoned"] == 1
    trip.refresh_from_db()
    assert trip.status == TripStatus.CANCELLED and trip.cancellation_fee == 0
    assert TripFlag.ABANDONED in trip.flags
    assert SupportTicket.objects.filter(trip=trip, priority="HIGH").exists()
    driver.refresh_from_db()
    assert driver.availability != "ON_TRIP"  # released
    assert verify_ledger()["balanced"]


def test_silent_driver_before_pickup_goes_back_to_dispatch(mini, make_driver, now, admin):
    driver = make_driver(now=now)
    trip = book(make_rider(), mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    Trip.objects.filter(pk=trip.pk).update(assigned_at=timezone.now() - timedelta(minutes=50))
    _silence(driver, 30)
    assert watchdog.sweep()["reassigned"] == 1
    trip.refresh_from_db()
    assert trip.status == TripStatus.REQUESTED and trip.driver is None


def test_old_stuck_trip_is_closed_even_if_its_ride_type_was_paused(mini, make_driver, now, admin):
    from apps.pricing.models import FareRule

    driver = make_driver(now=now)
    trip = book(make_rider(), mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    Trip.objects.filter(pk=trip.pk).update(
        requested_at=timezone.now() - timedelta(hours=6),
        assigned_at=timezone.now() - timedelta(hours=6),
    )
    _silence(driver, 300)
    FareRule.objects.filter(city=trip.city, ride_type=mini).update(is_active=False)
    assert watchdog.sweep()["closed"] == 1
    trip.refresh_from_db()
    assert trip.status == TripStatus.CANCELLED and trip.cancelled_by == "OPS"
