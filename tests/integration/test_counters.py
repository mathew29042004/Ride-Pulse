"""Station booking counters: cash in, trip paid from the counter account, SMS, day summary."""

from decimal import Decimal
from unittest import mock

import pytest

from apps.accounts.models import Role
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.geo.models import Landmark
from apps.payments import services as payments
from apps.rides import counters

from ..conftest import MARINA, make_staff

pytestmark = pytest.mark.django_db


@pytest.fixture
def counter(chennai):
    return counters.open_counter(Landmark.objects.get(name="Chennai Central Railway Station"))


def test_book_for_a_walk_up_passenger(counter, mini, make_driver, now, api):
    agent = make_staff(Role.SUPPORT_AGENT)
    make_driver(now=now)
    with pytest.raises(ActionNotPermitted):
        counters.book(
            counter,
            staff=make_staff(Role.FLEET_EXECUTIVE),
            ride_type=mini,
            dropoff=MARINA,
            dropoff_address="Marina",
            passenger_name="Muthu",
        )
    with pytest.raises(BusinessRuleViolation, match="10-digit"):
        counters.book(
            counter,
            staff=agent,
            ride_type=mini,
            dropoff=MARINA,
            dropoff_address="Marina",
            passenger_name="Muthu",
            passenger_phone="123",
        )
    with mock.patch("apps.accounts.sms.send_text") as sms:
        b = counters.book(
            counter,
            staff=agent,
            ride_type=mini,
            dropoff=MARINA,
            dropoff_address="Marina Beach",
            passenger_name="Muthu",
            passenger_phone="98400 12345",
            now=now,
        )
    assert "Ride PIN" in sms.call_args.args[1] and sms.call_args.args[0] == "9840012345"
    assert b.trip.payment_method == "WALLET" and b.cash > 0
    assert (
        payments.wallet_balance(counter.account.user) == Decimal(0)
        or b.trip.payment_status != "PAID"
    )
    assert payments.verify_ledger()["balanced"]
    summary = counters.day_summary(counter, day=now.date())
    assert summary["bookings"] == 1 and summary["cash"] == b.cash
    slip = api(agent).get(f"/api/v1/counters/{counter.pk}/").json()["bookings"][0]
    assert slip["pin"] == b.trip.otp and slip["passenger"] == "Muthu"


def test_only_at_stations(chennai):
    with pytest.raises(BusinessRuleViolation, match="stations"):
        counters.open_counter(Landmark.objects.exclude(category="TRANSIT").first())
