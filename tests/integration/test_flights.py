"""Flight-aware airport pickups: pickup follows landing + buffer, moves when the flight does,
cancels with the flight, and only works at airports."""

from datetime import timedelta

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.geo.models import Zone
from apps.rides import flights
from apps.rides import services as rides
from apps.rides.models import ScheduledRide

from ..conftest import MARINA, T_NAGAR

pytestmark = pytest.mark.django_db


@pytest.fixture
def airport(chennai):
    return Zone.objects.filter(city=chennai, is_airport=True).first()


def book(rider, mini, airport, now, flight="6e2134"):
    return rides.schedule_ride(
        rider=rider,
        ride_type=mini,
        pickup=(airport.center_lat, airport.center_lng),
        dropoff=MARINA,
        payment_method="UPI",
        scheduled_for=now + timedelta(hours=3),
        flight_number=flight,
        now=now,
    )


def test_pickup_follows_the_flight(rider, mini, airport, now, monkeypatch):
    arrival = now + timedelta(hours=3)
    delay = {"m": 0}
    monkeypatch.setattr(
        flights,
        "status",
        lambda f, a: {
            "state": "SCHEDULED",
            "landing": a + timedelta(minutes=delay["m"]),
            "delay_min": delay["m"],
        },
    )
    ride = book(rider, mini, airport, now)
    assert (
        ride.flight_number == "6E 2134" and ride.scheduled_for == arrival + flights.BAGGAGE_BUFFER
    )
    delay["m"] = 3
    assert flights.follow(now=now)["moved"] == 0  # under 5 minutes: leave it
    delay["m"] = 45
    assert flights.follow(now=now)["moved"] == 1
    ride.refresh_from_db()
    assert ride.scheduled_for == arrival + timedelta(minutes=45) + flights.BAGGAGE_BUFFER


def test_cancelled_flight_cancels_pickup(rider, mini, airport, now, monkeypatch):
    monkeypatch.setattr(
        flights, "status", lambda f, a: {"state": "CANCELLED", "landing": a, "delay_min": 0}
    )
    ride = book(rider, mini, airport, now)
    assert flights.follow(now=now)["cancelled"] == 1
    assert ScheduledRide.objects.get(pk=ride.pk).status == "CANCELLED"


def test_airports_only_and_valid_numbers(rider, mini, airport, now):
    with pytest.raises(BusinessRuleViolation, match="airport"):
        rides.schedule_ride(
            rider=rider,
            ride_type=mini,
            pickup=T_NAGAR,
            dropoff=MARINA,
            payment_method="UPI",
            scheduled_for=now + timedelta(hours=3),
            flight_number="AI 543",
            now=now,
        )
    with pytest.raises(BusinessRuleViolation, match="flight number"):
        book(rider, mini, airport, now, flight="hello")
    # The simulation is stable for the same flight and day.
    a = flights.status("AI 543", now)
    assert a == flights.status("AI 543", now)
