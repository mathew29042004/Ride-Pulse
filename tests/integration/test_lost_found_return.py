"""Lost & found, extended: valuables are urgent, a found item comes back as a parcel, and
uncollected items go to the hub and are donated after 30 days."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.drivers import services as drivers
from apps.rides import dispatch, lost_items
from apps.rides import services as rides
from apps.rides.models import LostItemReport, LostItemStatus, TripStatus
from apps.support.models import SupportTicket

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db


def _found(rider, mini, driver, now, category="PHONE"):
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    item = lost_items.report(trip, user=rider.user, description="Black phone", category=category)
    item = lost_items.driver_answer(item, user=driver.user, found=True)
    return trip, item


def test_valuables_are_urgent(mini, make_driver, now):
    driver = make_driver(now=now)
    _, item = _found(make_rider(), mini, driver, now)
    assert SupportTicket.objects.get(pk=item.ticket_id).priority == "URGENT"
    assert item.found_at is not None


def test_found_item_comes_back_as_a_parcel(make_driver, mini, now):
    driver = make_driver(now=now)
    courier = make_driver(now=now, ride_type="BIKE")
    rider = make_rider()
    _, item = _found(rider, mini, driver, now)
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=timezone.now())
    parcel = lost_items.request_delivery(
        item, user=rider.user, dropoff=MARINA, dropoff_address="Home", now=timezone.now()
    )
    item.refresh_from_db()
    assert item.status == LostItemStatus.ON_THE_WAY and item.return_trip == parcel
    assert parcel.service == "PARCEL" and parcel.rider == rider
    # The courier picks it up from the driver and delivers it: the item is returned.
    t = timezone.now()
    drivers.update_location(courier, lat=T_NAGAR[0], lng=T_NAGAR[1], now=t)
    dispatch.sweep(now=t)
    offer = pending_offer(parcel)
    parcel = dispatch.accept_offer(offer, driver=offer.driver, now=t)
    who = offer.driver
    drivers.update_location(who, lat=parcel.pickup_lat, lng=parcel.pickup_lng, now=t)
    parcel = rides.mark_arrived(parcel, driver=who, now=t)
    parcel = rides.start_trip(parcel, driver=who, otp=parcel.otp, now=t)
    drivers.update_location(who, lat=parcel.dropoff_lat, lng=parcel.dropoff_lng, now=t)
    parcel = rides.complete_delivery(
        parcel, driver=who, delivery_code=parcel.parcel.delivery_code, now=t + timedelta(minutes=20)
    )
    assert parcel.status == TripStatus.COMPLETED
    item.refresh_from_db()
    assert item.status == LostItemStatus.RETURNED and item.closed_at


def test_uncollected_goes_to_the_hub_then_is_donated(mini, make_driver, now):
    driver = make_driver(now=now)
    _, item = _found(make_rider(), mini, driver, now, category="BAG")
    LostItemReport.objects.filter(pk=item.pk).update(found_at=timezone.now() - timedelta(days=8))
    assert lost_items.sweep()["to_hub"] == 1
    item.refresh_from_db()
    assert item.status == LostItemStatus.AT_HUB
    LostItemReport.objects.filter(pk=item.pk).update(hub_at=timezone.now() - timedelta(days=31))
    assert lost_items.sweep()["disposed"] == 1
    item.refresh_from_db()
    assert item.status == LostItemStatus.DISPOSED


def test_ops_lost_and_found(api, mini, make_driver, now):
    from apps.accounts.models import Role

    from ..conftest import make_staff

    driver = make_driver(now=now)
    _, item = _found(make_rider(), mini, driver, now)
    client = api(make_staff(Role.SUPPORT_AGENT))
    rows = client.get("/api/v1/ops/lost-found/").json()
    assert rows[0]["id"] == item.pk and rows[0]["driver_name"]
    assert client.post(f"/api/v1/ops/lost-found/{item.pk}/hub/").json()["status"] == "AT_HUB"
    assert client.post(f"/api/v1/ops/lost-found/{item.pk}/returned/").json()["status"] == "RETURNED"
    assert client.get("/api/v1/ops/lost-found/").json() == []
