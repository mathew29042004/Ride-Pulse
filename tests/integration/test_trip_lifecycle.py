from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core.exceptions import BusinessRuleViolation, ConflictError, InvalidStateTransition
from apps.drivers.models import Availability
from apps.payments.services import verify_ledger, wallet_balance
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import OfferStatus, PricingMode, Trip, TripFlag, TripStatus

from ..conftest import T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db


def test_full_trip_happy_path(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    assert trip.status == TripStatus.REQUESTED
    assert trip.pickup_zone.name == "T. Nagar"
    offer = pending_offer(trip)
    assert offer.driver == driver

    trip = drive_to_completion(trip, now=now)
    assert trip.status == TripStatus.COMPLETED
    assert trip.pricing_mode == PricingMode.UPFRONT
    assert trip.fare_total == trip.estimated_fare  # the upfront price is honoured
    assert trip.payment_status == "PAID"
    driver.refresh_from_db()
    assert driver.availability == Availability.ONLINE
    assert driver.completed_trips == 1
    assert wallet_balance(driver.user) == trip.driver_earning
    assert verify_ledger()["balanced"]
    statuses = list(trip.events.filter(kind="STATUS").values_list("to_status", flat=True))
    assert statuses == [
        "REQUESTED",
        "DRIVER_ASSIGNED",
        "DRIVER_ARRIVED",
        "IN_PROGRESS",
        "COMPLETED",
    ]


def test_wrong_ride_pin_is_rejected(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now, enforce_distance=False)
    wrong = "0000" if trip.otp != "0000" else "1111"
    with pytest.raises(BusinessRuleViolation, match="ride PIN"):
        rides.start_trip(trip, driver=driver, otp=wrong, now=now)
    assert Trip.objects.get(pk=trip.pk).status == TripStatus.DRIVER_ARRIVED


def test_driver_must_be_near_pickup_to_arrive(rider, mini, make_driver, now):
    driver = make_driver(at=(T_NAGAR[0] + 0.02, T_NAGAR[1]), now=now)  # ~2.2 km away
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    with pytest.raises(BusinessRuleViolation, match="from the pickup"):
        rides.mark_arrived(trip, driver=driver, now=now)


def test_long_detour_is_repriced_and_flagged(rider, mini, make_driver, now):
    make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = drive_to_completion(trip, now=now, distance=trip.estimated_distance_km * 2)
    assert trip.pricing_mode == PricingMode.METERED
    assert trip.fare_total > trip.estimated_fare
    assert TripFlag.ROUTE_DEVIATION in trip.flags


def test_billed_distance_ignores_the_drive_to_pickup(rider, mini, make_driver, now):
    from apps.drivers import services as drivers

    driver = make_driver(at=(T_NAGAR[0] + 0.02, T_NAGAR[1]), now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    drivers.update_location(
        driver, lat=T_NAGAR[0] + 0.01, lng=T_NAGAR[1], now=now + timedelta(minutes=2)
    )
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now + timedelta(minutes=4))
    trip = rides.mark_arrived(trip, driver=driver, now=now + timedelta(minutes=4))
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now + timedelta(minutes=5))
    drivers.update_location(
        driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now + timedelta(minutes=20)
    )
    trip = rides.complete_trip(trip, driver=driver, now=now + timedelta(minutes=21))
    # Only the T. Nagar → Marina leg counts (~5 km straight line), not the 2.2 km to the pickup.
    assert trip.actual_distance_km < Decimal("6.5")


def test_one_active_trip_per_rider(rider, mini, make_driver, now):
    make_driver(now=now)
    book(rider, mini, now=now)
    with pytest.raises(ConflictError):
        book(rider, mini, now=now)


def test_database_refuses_double_booking_a_driver(mini, make_driver, now):
    driver = make_driver(now=now)
    first = book(make_rider(), mini, now=now)
    dispatch.accept_offer(pending_offer(first), driver=driver, now=now)
    second = book(make_rider(), mini, now=now)
    # Even bypassing the services, PostgreSQL's partial unique index blocks a second active trip.
    with pytest.raises(IntegrityError), transaction.atomic():
        Trip.objects.filter(pk=second.pk).update(driver=driver, status=TripStatus.DRIVER_ASSIGNED)


def test_completed_trip_cannot_be_cancelled(rider, mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    with pytest.raises(InvalidStateTransition):
        rides.cancel_trip(trip, user=rider.user, now=now + timedelta(hours=1))


def test_ratings_update_profiles(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    rides.rate_trip(trip, user=rider.user, stars=3, now=trip.completed_at)
    rides.rate_trip(trip, user=driver.user, stars=4, now=trip.completed_at)
    driver.refresh_from_db()
    rider.refresh_from_db()
    assert driver.rating == Decimal("3.00") and driver.rating_count == 1
    assert rider.rating == Decimal("4.00")
    with pytest.raises(ConflictError):
        rides.rate_trip(trip, user=rider.user, stars=5, now=trip.completed_at)


def test_low_rating_flags_the_trip(rider, mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    rides.rate_trip(trip, user=rider.user, stars=1, now=trip.completed_at)
    trip.refresh_from_db()
    assert TripFlag.LOW_RATING in trip.flags


def test_tip_goes_entirely_to_the_driver(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    before = wallet_balance(driver.user)
    rides.tip_driver(trip, user=rider.user, amount=Decimal(50), method="UPI", now=trip.completed_at)
    assert wallet_balance(driver.user) == before + 50
    assert Trip.objects.get(pk=trip.pk).tip_amount == Decimal(50)
    assert verify_ledger()["balanced"]


def test_safety_score_from_telemetry(mini, make_driver, now):
    from apps.drivers import services as drivers

    driver = make_driver(now=now)
    for i in range(5):
        t = now + timedelta(hours=i)
        drivers.update_location(
            driver, lat=T_NAGAR[0] + 0.002, lng=T_NAGAR[1], now=t - timedelta(seconds=30)
        )
        trip = book(make_rider(), mini, now=t)
        trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=t)
        trip = rides.mark_arrived(trip, driver=driver, now=t, enforce_distance=False)
        trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=t + timedelta(minutes=1))
        rides.complete_trip(
            trip,
            driver=driver,
            now=t + timedelta(minutes=20),
            actual_distance_km=6,
            telemetry={"harsh_brakes": 3, "speeding_seconds": 200},
        )
    driver.refresh_from_db()
    assert driver.safety_score is not None and driver.safety_score < 80


def test_offers_never_go_to_a_busy_driver(mini, make_driver, now):
    driver = make_driver(now=now)
    first = book(make_rider(), mini, now=now)
    assert pending_offer(first).driver == driver
    second = book(make_rider(), mini, now=now)
    assert pending_offer(second) is None  # the only driver already holds a pending offer
    assert first.offers.filter(status=OfferStatus.PENDING).count() == 1


def test_bot_drivers_answer_the_riders_chat(rider, mini, make_driver, now):
    from apps.simulation.simulator import Simulator

    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip.refresh_from_db()
    sim = Simulator(city_slugs=["chennai"], drivers_per_city=0, seed=3, log=lambda *_: None)

    message = rides.send_message(trip, user=rider.user, body="Where are you?")
    sim._reply_to_chat(trip, driver, message.created_at + timedelta(seconds=1))
    assert trip.messages.count() == 1  # not instantly: a person takes a moment to type
    sim._reply_to_chat(trip, driver, message.created_at + timedelta(seconds=10))
    reply = trip.messages.last()
    assert reply.sender == "DRIVER" and reply.body in Simulator.CHAT_REPLIES[trip.status]
    sim._reply_to_chat(trip, driver, message.created_at + timedelta(seconds=20))
    assert trip.messages.count() == 2  # one reply per rider message


def test_trip_with_a_stop_is_priced_and_driven_through_it(rider, mini, make_driver, now):
    from apps.core.exceptions import BusinessRuleViolation
    from apps.geo.distance import haversine_km
    from apps.simulation.simulator import Simulator

    from ..conftest import MARINA

    stop = (13.0604, 80.2496)  # Nungambakkam, off the direct line
    direct = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now)
    via = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now, stop=stop)
    fare = lambda result: next(o for o in result["options"] if o["ride_type"] == mini)  # noqa: E731
    assert fare(via)["estimate"].fare.total > fare(direct)["estimate"].fare.total
    assert fare(via)["estimate"].route.distance_km > fare(direct)["estimate"].route.distance_km

    make_driver(now=now)
    trip = rides.request_trip(
        rider=rider,
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        stop=stop,
        stop_address="Nungambakkam",
        now=now,
    )
    assert trip.stop == stop and trip.waypoints[1] == stop
    assert trip.estimated_fare == fare(via)["estimate"].fare.total
    # Bots drive along a path that goes through the stop.
    path = Simulator._route(trip)
    assert min(haversine_km(*p, *stop) for p in path) < 0.01

    with pytest.raises(BusinessRuleViolation):  # a "stop" on top of the pickup is no stop
        rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now, stop=T_NAGAR)


def test_bot_riders_are_never_real_people():
    from apps.riders.services import register_rider
    from apps.simulation.simulator import Simulator

    register_rider(email="someone@gmail.com", password="pw-12345!", first_name="Real")
    register_rider(email="loadtest+1@ridepulse.dev", password="pw-12345!", first_name="Load")
    assert Simulator.pick_bot_rider() is None
    synthetic = register_rider(email="asha.rao@example.com", password=None, first_name="Asha")
    assert Simulator.pick_bot_rider() == synthetic
