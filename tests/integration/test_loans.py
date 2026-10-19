"""Vehicle loans: eligibility, the EMI maths, weekly collection before payouts (drivers keep a
minimum; shortfalls become arrears), early pay-off, and the ledger staying balanced."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import loans
from apps.drivers.models import DriverProfile
from apps.payments import accounts
from apps.payments import services as payments

pytestmark = pytest.mark.django_db


def test_emi_matches_the_formula():
    # ₹5,00,000 over 3 years at 14% a year, weekly: about ₹3,950 a week.
    value = loans.emi(Decimal(500_000), weeks=156)
    assert Decimal(3900) < value < Decimal(4000)
    assert loans.emi(Decimal(52_000), weeks=52, annual_rate=Decimal(0)) == Decimal(1000)


@pytest.fixture
def driver(make_driver, now, monkeypatch):
    d = make_driver(online=False)
    DriverProfile.objects.filter(pk=d.pk).update(
        completed_trips=400, approved_at=now - timedelta(days=200), rating=Decimal("4.8")
    )
    d.refresh_from_db()
    monkeypatch.setattr(loans, "average_weekly_earnings", lambda driver, **k: Decimal(12_000))
    return d


def credit(driver, amount):
    wallet = payments.ensure_wallet(driver.user)
    payments.post(
        "INCENTIVE", [(wallet, Decimal(amount)), (accounts.PLATFORM_PROMOTIONS, -Decimal(amount))]
    )


def test_apply_approve_collect_and_pay_off(driver, ops, now):
    info = loans.eligibility(driver, now=now)
    assert info["eligible"] and info["max_amount"] > 100_000
    with pytest.raises(BusinessRuleViolation, match="borrow between"):
        loans.apply(driver, vehicle="Tata Tiago EV", amount=info["max_amount"] + 1000, weeks=156)
    loan = loans.apply(driver, vehicle="Tata Tiago EV", amount=Decimal(100_000), weeks=104, now=now)
    with pytest.raises(BusinessRuleViolation, match="already"):
        loans.apply(driver, vehicle="Another", amount=Decimal(30_000), weeks=52, now=now)
    loans.decide(loan, approve=True, user=ops, now=now)

    credit(driver, 10_000)  # a good week: the full EMI comes out
    loans.collect(now=now)
    loan.refresh_from_db()
    assert loan.arrears == 0 and loan.outstanding < 100_000
    assert payments.wallet_balance(driver.user) == Decimal(10_000) - loan.repayments.get().amount

    # A bad week: ₹2,000 in the wallet. At most half, and ₹1,500 always kept → ₹500 taken.
    wallet = payments.ensure_wallet(driver.user)
    payments.post(
        "PAYOUT",
        [
            (wallet, -payments.wallet_balance(driver.user)),
            (accounts.PAYOUTS_IN_TRANSIT, payments.wallet_balance(driver.user)),
        ],
    )
    credit(driver, 2000)
    loans.collect(now=now + timedelta(days=7))
    loan.refresh_from_db()
    assert payments.wallet_balance(driver.user) == Decimal(1500)
    assert loan.arrears == loan.weekly_emi - Decimal(500)

    with pytest.raises(BusinessRuleViolation, match="need"):
        loans.pay_off(loan)
    credit(driver, int(loan.outstanding))
    loans.pay_off(loan)
    loan.refresh_from_db()
    assert loan.status == loans.LoanStatus.CLOSED and loan.outstanding == 0
    assert payments.verify_ledger()["balanced"]


def test_new_drivers_cannot_apply(make_driver, now):
    info = loans.eligibility(make_driver(online=False), now=now)
    assert not info["eligible"] and any("trips" in r for r in info["reasons"])


def test_api(api, driver, ops):
    client = api(driver.user)
    assert client.get("/api/v1/driver/loan/").json()["eligible"]
    made = client.post(
        "/api/v1/driver/loan/apply/",
        {"vehicle": "Bajaj RE auto", "amount": "50000", "weeks": 52},
        format="json",
    )
    assert made.status_code == 201
    ops_client = api(ops)
    assert ops_client.get("/api/v1/ops/loans/").json()["loans"][0]["id"] == made.json()["id"]
    decided = ops_client.post(
        f"/api/v1/ops/loans/{made.json()['id']}/decide/", {"approve": True}, format="json"
    )
    assert decided.json()["status"] == "ACTIVE"
    assert client.get("/api/v1/ops/loans/").status_code == 403
