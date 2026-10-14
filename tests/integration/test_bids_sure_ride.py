"""Bid your fare (offers and counter-offers) and Sure Ride."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.drivers import services as drivers
from apps.payments.services import verify_ledger, wallet_balance
from apps.rides import bids, dispatch
from apps.rides import services as rides
from apps.rides.models import OfferStatus, TripStatus

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import pending_offer

pytestmark = pytest.mark.django_db


def request(rider, mini, now, **kwargs):
    return rides.request_trip(
        rider=rider,
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        now=now,
        **kwargs,
    )


def usual_fare(mini, now):
    options = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    option = next(o for o in options["options"] if o["ride_type"] == mini)
    return option["estimate"].fare.total, option


def test_offer_must_be_in_range(mini, make_driver, now):
    make_driver(now=now)
    usual, option = usual_fare(mini, now)
    low, high = bids.offer_bounds(usual)
    assert option["offer_range"] == {"min": low, "max": high}
    with pytest.raises(BusinessRuleViolation, match="Offer between"):
        request(make_rider(), mini, now, fare_offer=low - 1)
    with pytest.raises(BusinessRuleViolation):
        request(make_rider(), mini, now, fare_offer=low, boost=10)


def test_low_offer_accepted_at_that_price(mini, make_driver, now):
    driver = make_driver(now=now)
    usual, _ = usual_fare(mini, now)
    offer_price = bids.offer_bounds(usual)[0]
    trip = request(make_rider(), mini, now, fare_offer=offer_price)
    assert trip.estimated_fare == offer_price and trip.offer_adjustment == offer_price - usual
    payload = dispatch.offer_payload(pending_offer(trip))
    assert payload["fare_offer"] == offer_price and payload["usual_fare"] == usual
    assert payload["counter_steps"] == ["10", "20", "30"]

    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    drivers.update_location(driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now)
    trip = rides.complete_trip(
        trip, driver=driver, now=now + timedelta(minutes=float(trip.estimated_duration_min))
    )
    assert trip.fare_total == offer_price  # upfront route: exactly the agreed price
    assert any(line.kind == "OFFER" for line in trip.final_fare.lines)
    assert verify_ledger()["balanced"]


def test_counter_offer_flow(mini, make_driver, now):
    first, second = make_driver(now=now), make_driver(now=now)
    usual, _ = usual_fare(mini, now)
    rider = make_rider()
    trip = request(rider, mini, now, fare_offer=bids.offer_bounds(usual)[0])
    offer = pending_offer(trip)
    countered = bids.counter(offer, driver=offer.driver, extra=Decimal(20), now=now)
    assert countered.status == OfferStatus.COUNTERED
    assert countered.counter_amount == trip.estimated_fare + 20
    nxt = pending_offer(trip)
    assert nxt and nxt.driver != offer.driver  # the search goes on at the rider's price
    assert [c.pk for c in bids.open_counters(trip, now)] == [offer.pk]
    with pytest.raises(BusinessRuleViolation):
        bids.counter(nxt, driver=nxt.driver, extra=Decimal(15), now=now)

    taken = bids.take_counter(countered, user=rider.user, now=now + timedelta(seconds=30))
    assert taken.status == TripStatus.DRIVER_ASSIGNED and taken.driver_id == offer.driver_id
    assert taken.estimated_fare == countered.counter_amount
    nxt.refresh_from_db()
    assert nxt.status == OfferStatus.WITHDRAWN
    assert {first.pk, second.pk} >= {offer.driver_id}


def test_counter_offers_expire(mini, make_driver, now):
    make_driver(now=now)
    usual, _ = usual_fare(mini, now)
    rider = make_rider()
    trip = request(rider, mini, now, fare_offer=bids.offer_bounds(usual)[0])
    offer = bids.counter(
        pending_offer(trip), driver=pending_offer(trip).driver, extra=Decimal(10), now=now
    )
    with pytest.raises(InvalidStateTransition, match="expired"):
        bids.take_counter(offer, user=rider.user, now=now + timedelta(minutes=3))


def test_counters_only_on_bids(mini, make_driver, now):
    make_driver(now=now)
    trip = request(make_rider(), mini, now)
    offer = pending_offer(trip)
    with pytest.raises(BusinessRuleViolation, match="only for rides where the rider bids"):
        bids.counter(offer, driver=offer.driver, extra=Decimal(10), now=now)


def test_sure_ride_on_time_costs_only_the_fee(mini, make_driver, now):
    driver = make_driver(now=now)
    _, option = usual_fare(mini, now)
    quote = option["sure_ride"]
    assert quote["minutes"] >= 6 and quote["fee"] == Decimal(5)
    rider = make_rider()
    trip = request(rider, mini, now, sure_ride=True)
    assert trip.sure_ride_minutes == quote["minutes"]
    assert any(line.code == "SURE_RIDE" for line in trip.estimate.lines)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    before = wallet_balance(rider.user)
    rides.mark_arrived(trip, driver=driver, now=now + timedelta(minutes=2))
    assert wallet_balance(rider.user) == before  # on time: no refund
    assert bids.sweep(now + timedelta(hours=1)) == 0


def test_sure_ride_late_driver_refunds(mini, make_driver, now):
    driver = make_driver(now=now)
    rider = make_rider()
    trip = request(rider, mini, now, sure_ride=True)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    before = wallet_balance(rider.user)
    late = trip.sure_ride_deadline + timedelta(minutes=1)
    assert bids.sweep(late) == 1  # not there yet: refunded without waiting for arrival
    assert wallet_balance(rider.user) == before + Decimal(30)
    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=late)
    rides.mark_arrived(trip, driver=driver, now=late)
    assert wallet_balance(rider.user) == before + Decimal(30)  # only once
    assert verify_ledger()["balanced"]


def test_sure_ride_no_driver_found_refunds_right_away(mini, make_driver, now):
    make_driver(now=now)
    rider = make_rider()
    trip = request(rider, mini, now, sure_ride=True)
    before = wallet_balance(rider.user)
    dispatch.sweep(now=trip.dispatch_deadline + timedelta(seconds=1))
    trip.refresh_from_db()
    assert trip.status == TripStatus.NO_DRIVER_FOUND and trip.sure_ride_refunded_at
    assert wallet_balance(rider.user) == before + Decimal(30)


def test_sure_ride_needs_a_driver_nearby(mini, now):
    with pytest.raises(BusinessRuleViolation, match="Sure Ride needs a driver"):
        request(make_rider(), mini, now, sure_ride=True)


def test_api(api, mini, make_driver, now):
    driver = make_driver(now=now)
    rider = make_rider()
    usual, _ = usual_fare(mini, now)
    client = api(rider.user)
    body = {
        "ride_type": "MINI",
        "payment_method": "UPI",
        "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1], "address": "T. Nagar"},
        "dropoff": {"lat": MARINA[0], "lng": MARINA[1], "address": "Marina"},
        "fare_offer": str(bids.offer_bounds(usual)[0]),
    }
    trip = client.post("/api/v1/trips/", body, format="json").json()
    offer = api(driver.user).get("/api/v1/driver/offer/").json()
    assert Decimal(str(offer["fare_offer"])) == Decimal(body["fare_offer"])
    assert (
        api(driver.user)
        .post(f"/api/v1/driver/offers/{offer['offer_id']}/counter/", {"extra": "20"})
        .status_code
        == 204
    )
    seen = client.get(f"/api/v1/trips/{trip['id']}/").json()
    assert len(seen["counter_offers"]) == 1
    counter = seen["counter_offers"][0]
    taken = client.post(f"/api/v1/trips/{trip['id']}/take-counter/", {"offer_id": counter["id"]})
    assert taken.json()["status"] == "DRIVER_ASSIGNED"
    assert taken.json()["estimated_fare"] == counter["counter_amount"]


def test_offer_floor_protects_the_drivers_share():
    upfront, driver = Decimal(200), Decimal(40)  # e.g. a short airport trip: mostly fees
    low, _ = bids.offer_bounds(upfront, driver)
    assert low == 180  # 85% would be 170, taking 30 of the driver's 40
    with pytest.raises(BusinessRuleViolation):
        bids.check_offer(upfront, Decimal(175), driver)
    assert bids.check_offer(upfront, Decimal(180), driver) == -20
