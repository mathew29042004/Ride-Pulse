"""Zero-commission day pass: a flat daily fee, and the driver keeps the whole fare."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.drivers import day_pass
from apps.drivers import services as drivers
from apps.payments import accounts
from apps.payments.services import account_balances, verify_ledger
from apps.rides import dispatch

from ..conftest import T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db


def test_day_pass_waives_commission_and_rider_pays_the_same(mini, make_driver, now):
    # Today at midday: a pass lasts until midnight, so trips mustn't run into tomorrow (and the
    # offer screen checks the pass against today's date).
    now = timezone.localtime(now).replace(hour=12, minute=0)
    driver = make_driver(now=now)
    first = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    assert first.platform_commission > 0 and first.commission_waived == 0

    with pytest.raises(BusinessRuleViolation):
        day_pass.buy(driver, method="CARD")
    bought = day_pass.buy(driver, method="UPI", payer_reference="driver@upi", now=now)
    assert bought.price == Decimal(49)  # a Mini
    assert account_balances()[accounts.PLATFORM_SUBSCRIPTIONS] == Decimal(49)
    with pytest.raises(ConflictError):
        day_pass.buy(driver, method="UPI", now=now)

    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    drivers_trip = book(make_rider(), mini, now=now)
    offer = dispatch.offer_payload(pending_offer(drivers_trip))
    assert offer["day_pass"] is True
    assert (
        offer["estimated_earning"]
        == drivers_trip.estimate.driver_earning + drivers_trip.estimate.platform_commission
    )
    second = drive_to_completion(drivers_trip, now=now)
    assert second.fare_total == first.fare_total  # same route, same price for the rider
    assert second.platform_commission == 0
    assert second.commission_waived == first.platform_commission
    assert second.driver_earning == first.driver_earning + first.platform_commission
    assert day_pass.status(driver, now)["kept_today"] == second.commission_waived
    assert verify_ledger()["balanced"]


def test_wallet_purchase_needs_earnings(make_driver, now):
    driver = make_driver(now=now)
    with pytest.raises(BusinessRuleViolation, match="Not enough earnings"):
        day_pass.buy(driver, method="WALLET", now=now)


def test_api(api, make_driver, now):
    driver = make_driver(now=now)
    client = api(driver.user)
    assert client.get("/api/v1/driver/day-pass/").json()["active_today"] is False
    body = client.post(
        "/api/v1/driver/day-pass/", {"method": "UPI", "payer_reference": "d@upi"}
    ).json()
    assert body["active_today"] is True and Decimal(str(body["price"])) == 49
