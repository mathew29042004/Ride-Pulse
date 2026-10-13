from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation, ConflictError, InvalidStateTransition
from apps.drivers.services import update_location
from apps.payments.services import verify_ledger, wallet_balance
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import CancelledBy, OfferStatus, Trip, TripStatus

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db


def test_nearest_compatible_driver_gets_the_offer(rider, mini, make_driver, now):
    far = make_driver(at=(T_NAGAR[0] + 0.03, T_NAGAR[1]), now=now)
    near = make_driver(at=(T_NAGAR[0] + 0.005, T_NAGAR[1]), now=now)
    make_driver(
        ride_type="SEDAN", at=(T_NAGAR[0] + 0.001, T_NAGAR[1]), now=now
    )  # closest, wrong type
    trip = book(rider, mini, now=now)
    assert pending_offer(trip).driver == near
    assert far != near


def test_stale_gps_drivers_are_skipped(rider, mini, make_driver, now):
    make_driver(now=now - timedelta(minutes=10))  # last ping 10 minutes ago
    trip = book(rider, mini, now=now)
    assert pending_offer(trip) is None


def test_decline_passes_the_trip_to_the_next_driver(rider, mini, make_driver, now):
    first = make_driver(at=(T_NAGAR[0] + 0.003, T_NAGAR[1]), now=now)
    second = make_driver(at=(T_NAGAR[0] + 0.02, T_NAGAR[1]), now=now)
    trip = book(rider, mini, now=now)
    dispatch.decline_offer(pending_offer(trip), driver=first, now=now + timedelta(seconds=5))
    assert pending_offer(trip).driver == second
    first.refresh_from_db()
    assert first.acceptance_rate == 0


def test_expired_offer_moves_on_and_request_eventually_times_out(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    result = dispatch.sweep(now=now + timedelta(seconds=25))
    assert result["offers_expired"] == 1
    assert trip.offers.get(driver=driver).status == OfferStatus.EXPIRED
    dispatch.sweep(now=trip.dispatch_deadline + timedelta(seconds=1))
    trip.refresh_from_db()
    assert trip.status == TripStatus.NO_DRIVER_FOUND


def test_late_acceptance_is_refused(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    with pytest.raises(Exception, match="expired"):
        dispatch.accept_offer(pending_offer(trip), driver=driver, now=now + timedelta(seconds=30))


def test_free_cancellation_within_two_minutes(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip = rides.cancel_trip(trip, user=rider.user, now=now + timedelta(seconds=60))
    assert trip.status == TripStatus.CANCELLED and trip.cancellation_fee == 0
    assert wallet_balance(rider.user) == 0
    driver.refresh_from_db()
    assert driver.availability == "ONLINE"


def test_late_rider_cancellation_charges_a_fee_shared_with_the_driver(
    rider, mini, make_driver, now
):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip = rides.cancel_trip(trip, user=rider.user, now=now + timedelta(minutes=5))
    assert trip.cancellation_fee == Decimal(50)
    assert wallet_balance(rider.user) == -50  # dues, to be paid before the next booking
    assert wallet_balance(driver.user) == Decimal(40)  # fee minus 20% commission
    assert verify_ledger()["balanced"]
    with pytest.raises(Exception, match="dues"):
        book(rider, mini, now=now + timedelta(minutes=10))


def test_driver_cancellation_redispatches_at_the_same_price(rider, mini, make_driver, now):
    first = make_driver(at=(T_NAGAR[0] + 0.003, T_NAGAR[1]), now=now)
    second = make_driver(at=(T_NAGAR[0] + 0.02, T_NAGAR[1]), now=now)
    trip = book(rider, mini, now=now)
    price = trip.estimated_fare
    trip = dispatch.accept_offer(pending_offer(trip), driver=first, now=now)
    trip = rides.cancel_trip(
        trip, user=first.user, reason="Flat tyre", now=now + timedelta(minutes=1)
    )
    assert trip.status == TripStatus.REQUESTED and trip.driver is None
    assert pending_offer(trip).driver == second
    assert trip.estimated_fare == price
    first.refresh_from_db()
    assert first.cancelled_trips == 1


def test_rider_no_show_lets_the_driver_cancel_with_a_fee(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip = rides.mark_arrived(
        trip, driver=driver, now=now + timedelta(minutes=3), enforce_distance=False
    )
    trip = rides.cancel_trip(trip, user=driver.user, now=now + timedelta(minutes=9))
    assert trip.status == TripStatus.CANCELLED
    assert trip.cancelled_by == CancelledBy.DRIVER and trip.cancellation_fee > 0


def test_ops_can_cancel_a_trip_in_progress_without_a_fee(rider, mini, make_driver, ops, now):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    with pytest.raises(Exception, match="in progress"):
        rides.cancel_trip(trip, user=rider.user, now=now)
    trip = rides.cancel_trip(trip, user=ops, reason="Safety escalation", now=now)
    assert trip.cancelled_by == CancelledBy.OPS and trip.cancellation_fee == 0


def test_batched_dispatch_minimises_total_pickup_time(mini, make_driver, now, settings):
    settings.RIDE_PULSE = {**settings.RIDE_PULSE, "DISPATCH_MODE": "BATCHED"}
    # Driver A sits between both riders; driver B is near rider 2 only. Greedy (rider 1 first)
    # would give A to rider 1 and send B far away; the assignment solver pairs them crosswise.
    rider1, rider2 = make_rider(), make_rider()
    a = make_driver(at=(13.0418, 80.2400), now=now)
    b = make_driver(at=(13.0418, 80.2650), now=now)
    t1 = book(rider1, mini, now=now, pickup=(13.0418, 80.2341))
    t2 = book(rider2, mini, now=now, pickup=(13.0418, 80.2600))
    assert not Trip.objects.get(pk=t1.pk).offers.exists()  # batched mode waits for the sweep
    offers = dispatch.batch_dispatch(t1.city, now=now)
    assignment = {o.trip_id: o.driver_id for o in offers}
    assert assignment == {t1.pk: a.pk, t2.pk: b.pk}
    assert all(o.dispatch_mode == "BATCHED" for o in offers)


def test_scheduled_ride_becomes_a_trip_shortly_before_pickup(rider, mini, make_driver, now):
    from apps.rides.models import ScheduledRide, ScheduledRideStatus

    def schedule(at, **kwargs):
        return rides.schedule_ride(
            rider=rider,
            ride_type=mini,
            pickup=T_NAGAR,
            dropoff=MARINA,
            payment_method="UPI",
            scheduled_for=at,
            now=now,
            **kwargs,
        )

    with pytest.raises(BusinessRuleViolation):
        schedule(now + timedelta(minutes=5))  # too soon: book now instead
    with pytest.raises(BusinessRuleViolation):
        schedule(now + timedelta(days=8))
    ride = schedule(now + timedelta(hours=2), dropoff_address="Marina Beach")
    assert ride.status == ScheduledRideStatus.SCHEDULED and ride.quoted_fare > 0
    with pytest.raises(ConflictError):
        schedule(now + timedelta(hours=2, minutes=10))  # overlaps the first

    # Nothing goes out early...
    assert rides.dispatch_scheduled_rides(now=now + timedelta(hours=1)) == {
        "dispatched": 0,
        "failed": 0,
    }
    # ...then, a few minutes before pickup, it becomes an ordinary trip request.
    make_driver(now=now + timedelta(hours=1, minutes=55))
    due = now + timedelta(hours=1, minutes=55)
    assert rides.dispatch_scheduled_rides(now=due)["dispatched"] == 1
    ride.refresh_from_db()
    assert ride.status == ScheduledRideStatus.DISPATCHED
    assert ride.trip.status == TripStatus.REQUESTED and ride.trip.dropoff_address == "Marina Beach"
    assert rides.dispatch_scheduled_rides(now=due)["dispatched"] == 0  # exactly once

    # A ride that can't be booked (the rider already has a trip) fails with a reason.
    clash = ScheduledRide.objects.create(
        **{
            f.name: getattr(ride, f.name)
            for f in ScheduledRide._meta.fields
            if f.name not in ("id", "trip", "status", "created_at", "updated_at")
        }
    )
    assert rides.dispatch_scheduled_rides(now=due)["failed"] == 1
    clash.refresh_from_db()
    assert clash.status == ScheduledRideStatus.FAILED and clash.failure_reason

    later = schedule(now + timedelta(days=1))
    assert rides.cancel_scheduled_ride(later, user=rider.user).status == "CANCELLED"
    with pytest.raises(InvalidStateTransition):
        rides.cancel_scheduled_ride(later, user=rider.user)


def test_scheduled_rides_api(api, rider, now):
    from django.utils import timezone as tz

    client = api(rider.user)
    when = (tz.now() + timedelta(hours=3)).isoformat()
    payload = {
        "ride_type": "AUTO",
        "payment_method": "CASH",
        "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1], "address": "T. Nagar"},
        "dropoff": {"lat": MARINA[0], "lng": MARINA[1], "address": "Marina Beach"},
        "scheduled_for": when,
    }
    created = client.post("/api/v1/scheduled-rides/", payload, format="json")
    assert created.status_code == 201, created.json()
    ride = created.json()
    assert ride["status"] == "SCHEDULED" and ride["ride_type_name"] == "Auto"
    assert [r["id"] for r in client.get("/api/v1/scheduled-rides/").json()["results"]] == [
        ride["id"]
    ]
    cancelled = client.post(f"/api/v1/scheduled-rides/{ride['id']}/cancel/").json()
    assert cancelled["status"] == "CANCELLED"
    # Other riders can't see it.
    assert api(make_rider().user).get(f"/api/v1/scheduled-rides/{ride['id']}/").status_code == 404
