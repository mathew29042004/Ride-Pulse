"""A rider books, chats with the driver, and finishes a trip, in a real browser."""

import pytest

pytest.importorskip("playwright", reason="install requirements/dev.txt for browser tests")
from playwright.sync_api import expect

from apps.drivers import services as drivers
from apps.riders.services import register_rider
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import TripMessage, TripStatus

from ..conftest import MARINA, T_NAGAR

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PASSWORD = "e2e-test-pass-2026"


def test_rider_books_chats_and_completes_a_trip(page, live_server, make_driver, now):
    register_rider(
        email="e2e.rider@test.dev", password=PASSWORD, first_name="Asha", phone="9800000001"
    )
    driver = make_driver(now=now)

    # Sign in.
    page.goto(f"{live_server.url}/login")
    page.get_by_placeholder("you@example.com").fill("e2e.rider@test.dev")
    page.get_by_placeholder("••••••••").fill(PASSWORD)
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page.get_by_text("Where to?")).to_be_visible()

    # Book a Mini to Marina Beach with an upfront fare.
    page.goto(f"{live_server.url}/ride/book?to={MARINA[0]},{MARINA[1]}&name=Marina%20Beach")
    book = page.get_by_role("button", name="Book Mini")
    expect(book).to_be_enabled()
    book.click()
    expect(page.get_by_text("Finding your Mini")).to_be_visible()
    trip = rides.Trip.objects.get(rider__user__email="e2e.rider@test.dev")

    # The driver accepts; the rider's screen updates on its own (polling, no reload).
    dispatch.accept_offer(trip.offers.get(), driver=driver)
    expect(page.get_by_text("Arriving in")).to_be_visible()
    trip.refresh_from_db()
    expect(page.get_by_text(trip.vehicle.registration_display)).to_be_visible()  # the plate

    # Chat with the driver using a quick reply.
    page.get_by_role("button", name="Message").click()
    with page.expect_response(
        lambda r: "/messages/" in r.url and r.request.method == "POST"
    ) as sent:
        page.get_by_role("button", name="I'm at the pickup point").click()
    assert sent.value.status == 201
    assert TripMessage.objects.get(trip=trip).body == "I'm at the pickup point"
    expect(page.get_by_text("Sending…")).to_have_count(0)  # the bubble is confirmed
    page.get_by_role("button", name="Close chat").click()

    # The driver arrives, starts with the rider's PIN and finishes the trip.
    trip.refresh_from_db()
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng)
    rides.mark_arrived(trip, driver=driver)
    expect(page.get_by_text("Your driver is here")).to_be_visible()
    rides.start_trip(trip, driver=driver, otp=trip.otp)
    expect(page.get_by_text("to drop")).to_be_visible()
    rides.complete_trip(trip, driver=driver, payer_reference="asha@upi")
    expect(page.get_by_text("Trip completed")).to_be_visible()
    assert rides.Trip.objects.get(pk=trip.pk).status == TripStatus.COMPLETED


def test_shared_trip_link_works_without_signing_in(page, live_server, rider, make_driver, now):
    driver = make_driver(now=now)
    trip = rides.request_trip(
        rider=rider,
        ride_type=rides.RideType.objects.get(code="MINI"),
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        dropoff_address="Marina Beach",
        now=now,
    )
    dispatch.accept_offer(trip.offers.get(), driver=driver, now=now)
    token = rides.share_trip(trip, user=rider.user)

    page.goto(f"{live_server.url}/track/{token}")
    expect(page.get_by_text(f"Driver on the way to {rider.user.first_name}")).to_be_visible()
    expect(page.get_by_text("Marina Beach")).to_be_visible()
    page.goto(f"{live_server.url}/track/not-a-real-link")
    expect(page.get_by_text("This link has expired")).to_be_visible()
