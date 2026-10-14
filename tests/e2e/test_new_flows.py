"""The newer rider flows in a real browser: parcels, fare bids with counter-offers, rentals,
Ride Check, switching away from an unavailable ride type, and the ops Team page."""

import re
from decimal import Decimal

import pytest

pytest.importorskip("playwright", reason="install requirements/dev.txt for browser tests")
from playwright.sync_api import expect

from apps.accounts.models import Role
from apps.drivers import services as drivers
from apps.pricing.models import RideType
from apps.riders.services import register_rider
from apps.rides import bids, dispatch
from apps.rides import services as rides
from apps.rides.models import RideCheck, RideCheckKind, RideCheckStatus, Trip, TripStatus

from ..conftest import MARINA, make_staff

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PASSWORD = "e2e-test-pass-2026"
DROP = f"to={MARINA[0]},{MARINA[1]}&name=Marina%20Beach"


def sign_in(page, live_server, email: str) -> None:
    page.goto(f"{live_server.url}/login")
    page.get_by_role("tab", name="Email").click()
    page.get_by_placeholder("you@example.com").fill(email)
    page.get_by_placeholder("••••••••").fill(PASSWORD)
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page).not_to_have_url(re.compile(r"/login"))  # signed in before moving on


def rider_account(n: int):
    return register_rider(
        email=f"e2e.rider{n}@test.dev",
        password=PASSWORD,
        first_name="Asha",
        phone=f"98000001{n:02d}",
    )


def bike(make_driver, now):
    return make_driver(ride_type="BIKE", now=now)


def test_send_a_parcel_and_deliver_it_with_the_code(page, live_server, make_driver, now):
    rider = rider_account(1)
    courier = bike(make_driver, now)
    sign_in(page, live_server, rider.user.email)
    expect(page.get_by_text("Where to?")).to_be_visible()

    page.goto(f"{live_server.url}/ride/book?service=PARCEL&{DROP}")
    page.get_by_placeholder("Meena").fill("Meena")
    page.get_by_placeholder("98765 43210").fill("9876512345")
    page.get_by_role("button", name="Keys").click()
    page.get_by_role("button", name="Book Parcel").click()
    expect(page.get_by_text("Finding your Parcel")).to_be_visible()

    trip = Trip.objects.get(rider=rider)
    assert trip.service == "PARCEL" and trip.parcel.category == "KEYS"
    trip = dispatch.accept_offer(trip.offers.get(), driver=courier)
    expect(page.get_by_text(trip.parcel.delivery_code)).to_be_visible()  # the code to pass on

    drivers.update_location(courier, lat=trip.pickup_lat, lng=trip.pickup_lng)
    trip = rides.mark_arrived(trip, driver=courier)
    trip = rides.start_trip(trip, driver=courier, otp=trip.otp)
    drivers.update_location(courier, lat=trip.dropoff_lat, lng=trip.dropoff_lng)
    rides.complete_delivery(trip, driver=courier, delivery_code=trip.parcel.delivery_code)
    expect(page.get_by_text("Delivered")).to_be_visible()


def test_bid_a_lower_fare_and_take_a_counter_offer(page, live_server, make_driver, now):
    rider = rider_account(2)
    driver = make_driver(now=now)
    sign_in(page, live_server, rider.user.email)
    expect(page.get_by_text("Where to?")).to_be_visible()

    page.goto(f"{live_server.url}/ride/book?{DROP}&type=MINI")
    page.get_by_role("switch", name="Offer your fare").click()
    for _ in range(3):
        page.get_by_role("button", name="−₹5").click()
    page.get_by_role("button", name="Book Mini").click()
    expect(page.get_by_text("Your offer:")).to_be_visible()

    trip = Trip.objects.get(rider=rider)
    assert trip.fare_offer is not None and trip.offer_adjustment < 0
    offer = trip.offers.get()
    countered = bids.counter(offer, driver=driver, extra=Decimal(20))
    page.get_by_role("button", name=f"₹{countered.counter_amount}").click()
    expect(page.get_by_text("Arriving in")).to_be_visible()
    trip.refresh_from_db()
    assert (
        trip.status == TripStatus.DRIVER_ASSIGNED
        and trip.estimated_fare == countered.counter_amount
    )


def test_book_an_hourly_rental(page, live_server, make_driver, now):
    rider = rider_account(3)
    make_driver(now=now)
    sign_in(page, live_server, rider.user.email)
    expect(page.get_by_text("Where to?")).to_be_visible()

    page.goto(f"{live_server.url}/ride/packages?service=RENTAL")
    page.get_by_role("button", name="4 h").click()
    expect(page.get_by_text("4 h / 40 km package")).to_be_visible()  # the fare breakdown
    page.get_by_role("button", name="Book Mini").click()
    expect(page.get_by_text("Finding your Mini")).to_be_visible()
    trip = Trip.objects.get(rider=rider)
    assert trip.service == "RENTAL" and trip.package_hours == 4 and trip.package_km == 40


def test_rider_answers_a_ride_check(page, live_server, make_driver, now):
    rider = rider_account(4)
    driver = make_driver(now=now)
    trip = rides.request_trip(
        rider=rider,
        ride_type=RideType.objects.get(code="MINI"),
        pickup=(driver.current_lat, driver.current_lng),
        dropoff=MARINA,
        payment_method="UPI",
    )
    trip = dispatch.accept_offer(trip.offers.get(), driver=driver)
    trip = rides.mark_arrived(trip, driver=driver)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp)
    check = RideCheck.objects.create(trip=trip, kind=RideCheckKind.LONG_STOP)

    sign_in(page, live_server, rider.user.email)
    page.goto(f"{live_server.url}/ride/trips/{trip.pk}/")
    expect(page.get_by_text("Is everything OK?")).to_be_visible()
    page.get_by_role("button", name="I'm OK").click()
    expect(page.get_by_text("Is everything OK?")).to_have_count(0)
    check.refresh_from_db()
    assert check.status == RideCheckStatus.OK


def test_unavailable_ride_type_suggests_a_switch(page, live_server, make_driver, now):
    rider = rider_account(5)
    make_driver(now=now)  # a Mini nearby
    make_driver(ride_type="BIKE", online=False)  # the city has bikes, but none are around
    sign_in(page, live_server, rider.user.email)
    expect(page.get_by_text("Where to?")).to_be_visible()

    page.goto(f"{live_server.url}/ride/book?{DROP}&type=BIKE")
    expect(page.get_by_text("No Bike drivers near you right now")).to_be_visible()
    page.get_by_role("button", name="Switch to Mini").click()
    expect(page.get_by_role("button", name="Book Mini")).to_be_enabled()


def test_ops_team_page_shows_the_org_chart(page, live_server):
    from apps.simulation.network import NetworkBuilder

    admin = make_staff(Role.ADMIN, email="e2e.admin@test.dev")
    admin.set_password(PASSWORD)
    admin.is_superuser = True
    admin.save()
    builder = NetworkBuilder(log=lambda *_: None)
    from apps.geo.models import City

    builder.build_org(
        {
            c.slug: c
            for c in City.objects.filter(
                slug__in=["chennai", "kochi", "bengaluru", "visakhapatnam"]
            )
        }
    )
    sign_in(page, live_server, admin.email)
    page.goto(f"{live_server.url}/ops/team")
    expect(page.get_by_text("Reporting lines · Tamil Nadu")).to_be_visible()
    expect(page.get_by_text("Regional Manager, Tamil Nadu")).to_be_visible()
