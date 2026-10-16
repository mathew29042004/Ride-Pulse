"""Tour packages: the catalogue, the fixed price, booking rules, the driver assigned ahead, the
day itself (stops, completion at the booked price), fallback dispatch, cancellation and rating."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.drivers import services as drivers
from apps.drivers.models import Vehicle, VehicleCondition
from apps.payments import services as payments
from apps.pricing.models import RideType
from apps.rides import services as rides
from apps.rides.models import TripStatus
from apps.tours import services as tours
from apps.tours.models import BookingStatus, TourPackage

from ..conftest import T_NAGAR, make_rider
from .helpers import pending_offer

pytestmark = pytest.mark.django_db


@pytest.fixture
def mahabs(chennai):
    return TourPackage.objects.get(slug="chennai-mahabalipuram-heritage")


def test_every_city_has_tours_with_real_stops():
    from apps.geo.models import City

    assert not City.objects.exclude(tours__isnull=False).exists()
    package = TourPackage.objects.get(slug="bengaluru-mysuru-royal-day-trip")
    assert [s.name for s in package.stops.all()][1] == "Mysuru Palace"


def test_price_is_fixed_by_route_time_and_car(mahabs, mini):
    suv = RideType.objects.get(code="SUV")
    r = tours.route(mahabs)
    assert 90 < r["km"] < 160 and r["stops"] == 4
    small, big = tours.tour_fare(mahabs, mini), tours.tour_fare(mahabs, suv)
    assert big.total > small.total > 1000
    assert {line.code for line in small.lines} >= {"TOUR", "TOUR_TIME", "BOOKING_FEE", "GST"}
    mahabs.price_adjust_percent = -20
    assert tours.tour_fare(mahabs, mini).total < small.total  # season offer
    with pytest.raises(BusinessRuleViolation, match="cars"):
        tours.tour_fare(mahabs, RideType.objects.get(code="AUTO"))
    codes = [q["ride_type"] for q in tours.quotes(mahabs)]
    assert "MINI" in codes and "AUTO" not in codes


def test_booking_rules(mahabs, mini, now):
    rider = make_rider()
    soon = now + timedelta(hours=2)
    with pytest.raises(BusinessRuleViolation, match="4 hours ahead"):
        tours.book(rider=rider, package=mahabs, ride_type=mini, depart_at=soon, pickup=T_NAGAR)
    with pytest.raises(BusinessRuleViolation, match="seats"):
        tours.book(
            rider=rider,
            package=mahabs,
            ride_type=mini,
            depart_at=now + timedelta(days=3),
            pickup=T_NAGAR,
            group_size=6,
        )
    with pytest.raises(BusinessRuleViolation, match="starts in Chennai"):
        tours.book(
            rider=rider,
            package=mahabs,
            ride_type=mini,
            depart_at=now + timedelta(days=3),
            pickup=(12.972, 77.62),  # Bengaluru
        )
    booking = tours.book(
        rider=rider,
        package=mahabs,
        ride_type=mini,
        depart_at=now + timedelta(days=3),
        pickup=T_NAGAR,
    )
    assert booking.status == BookingStatus.BOOKED and booking.driver is None  # assigned later
    with pytest.raises(ConflictError, match="that day"):
        tours.book(
            rider=rider,
            package=mahabs,
            ride_type=mini,
            depart_at=now + timedelta(days=3, hours=1),
            pickup=T_NAGAR,
        )


def _tour_tomorrow(mahabs, mini, now, make_driver):
    best = make_driver(now=now)
    other = make_driver(now=now)
    type(best).objects.filter(pk=best.pk).update(rating=Decimal("4.95"))
    type(other).objects.filter(pk=other.pk).update(rating=Decimal("4.50"))
    rider = make_rider()
    booking = tours.book(
        rider=rider,
        package=mahabs,
        ride_type=mini,
        depart_at=now + timedelta(hours=20),
        pickup=T_NAGAR,
        pickup_address="T. Nagar",
        group_size=3,
    )
    return booking, best, other, rider


def test_driver_assigned_ahead_by_rating_and_decline_passes_it_on(mahabs, mini, now, make_driver):
    booking, best, other, _ = _tour_tomorrow(mahabs, mini, now, make_driver)
    assert booking.status == BookingStatus.ASSIGNED and booking.driver == best
    tours.decline(booking, driver=best, now=now)
    booking.refresh_from_db()
    assert booking.driver == other and best.pk in booking.declined_by
    # An unsafe car isn't given a tour.
    Vehicle.objects.filter(driver=other).update(condition=VehicleCondition.OFF_ROAD)
    assert not tours.candidates(booking).filter(pk=other.pk).exists()


def test_the_tour_day_runs_at_the_booked_price(mahabs, mini, now, make_driver):
    booking, best, _, rider = _tour_tomorrow(mahabs, mini, now, make_driver)
    depart = booking.depart_at
    drivers.go_offline(best, now=now)
    with pytest.raises(BusinessRuleViolation, match="within 2 hours"):
        tours.start(booking, driver=best, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    trip = tours.start(
        booking, driver=best, lat=T_NAGAR[0], lng=T_NAGAR[1], now=depart - timedelta(minutes=30)
    )
    booking.refresh_from_db()
    assert booking.status == BookingStatus.STARTED and trip.driver == best
    assert trip.service == "INTERCITY" and trip.round_trip and trip.estimated_fare == booking.price

    t = depart
    drivers.update_location(best, lat=trip.pickup_lat, lng=trip.pickup_lng, now=t)
    trip = rides.mark_arrived(trip, driver=best, now=t)
    trip = rides.start_trip(trip, driver=best, otp=trip.otp, now=t + timedelta(minutes=2))
    with pytest.raises(BusinessRuleViolation, match="reached first"):
        tours.mark_stop(booking, driver=best, order=1, event="left", now=t)
    for stop in mahabs.stops.all():
        tours.mark_stop(booking, driver=best, order=stop.order, event="arrived", now=t)
        tours.mark_stop(booking, driver=best, order=stop.order, event="left", now=t)
    booking.refresh_from_db()
    assert set(booking.progress) == {"1", "2", "3", "4"}

    end = t + timedelta(hours=8)
    drivers.update_location(best, lat=trip.pickup_lat, lng=trip.pickup_lng, now=end)
    trip = rides.complete_trip(
        trip, driver=best, actual_distance_km=Decimal("150"), now=end, payer_reference="tour@upi"
    )
    assert trip.status == TripStatus.COMPLETED and trip.fare_total == booking.price
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED
    tours.rate(booking, user=rider.user, stars=5, review="Lovely guide")
    mahabs.refresh_from_db()
    assert mahabs.rating == 5.0
    with pytest.raises(ConflictError):
        tours.rate(booking, user=rider.user, stars=4)
    assert payments.verify_ledger()["balanced"]


def test_no_show_driver_falls_back_to_dispatch(mahabs, mini, now, make_driver):
    booking, best, other, _ = _tour_tomorrow(mahabs, mini, now, make_driver)
    late = booking.depart_at - timedelta(minutes=10)
    drivers.go_offline(best, now=now)
    drivers.go_offline(other, now=now)  # rested overnight, back online just before the tour
    drivers.go_online(other, lat=T_NAGAR[0], lng=T_NAGAR[1], now=late)
    result = tours.sweep(now=late)
    from apps.rides import dispatch

    dispatch.sweep(now=late)
    booking.refresh_from_db()
    assert result["dispatched"] == 1 and booking.status == BookingStatus.STARTED
    assert pending_offer(booking.trip).driver == other


def test_cancel_is_free_early_and_costs_a_quarter_late(mahabs, mini, now, make_driver):
    rider = make_rider()
    early = tours.book(
        rider=rider,
        package=mahabs,
        ride_type=mini,
        depart_at=now + timedelta(days=5),
        pickup=T_NAGAR,
    )
    assert tours.cancel(early, user=rider.user, now=now).cancellation_fee == 0
    booking, best, _, rider = _tour_tomorrow(mahabs, mini, now, make_driver)
    before = payments.wallet_balance(best.user)
    cancelled = tours.cancel(booking, user=rider.user, now=now)
    assert cancelled.status == BookingStatus.CANCELLED
    assert cancelled.cancellation_fee == (booking.price * Decimal("0.25")).quantize(Decimal("0.01"))
    assert payments.wallet_balance(best.user) > before  # the assigned driver keeps a share
    assert payments.verify_ledger()["balanced"]


def test_tour_api(api, mahabs, mini, now, make_driver):
    make_driver(now=now)
    rider = make_rider()
    client = api(rider.user)
    listing = client.get("/api/v1/tours/?city=chennai").json()
    assert any(p["slug"] == mahabs.slug for p in listing)
    detail = client.get(f"/api/v1/tours/{mahabs.slug}/").json()
    assert len(detail["stops"]) == 4 and detail["quotes"]
    response = client.post(
        f"/api/v1/tours/{mahabs.slug}/book/",
        {
            "ride_type": "MINI",
            "depart_at": (now + timedelta(hours=20)).isoformat(),
            "pickup_lat": T_NAGAR[0],
            "pickup_lng": T_NAGAR[1],
            "group_size": 2,
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    mine = client.get("/api/v1/tours/bookings/").json()
    assert mine[0]["status"] == "ASSIGNED" and mine[0]["driver"]["name"]
