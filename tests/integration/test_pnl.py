"""City P&L: revenue and promotion spend tie to the ledger by trip city; estimates are labelled;
GST is kept out of revenue; budgets compare; finance-only."""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.analytics import pnl
from apps.payments.models import LedgerEntry

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


def test_pnl_ties_to_the_ledger(api, mini, make_driver, now, chennai):
    make_driver(now=now)
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    month = timezone.localdate().replace(day=1)
    report = pnl.report(month)
    row = next(r for r in report["cities"] if r["city"] == "Chennai")
    commission = sum(
        e.amount
        for e in LedgerEntry.objects.filter(transaction__trip=trip, account="platform:commission")
    )
    assert Decimal(row["commission"]) == commission > 0
    gst = sum(
        e.amount
        for e in LedgerEntry.objects.filter(transaction__trip=trip, account="tax:gst_payable")
    )
    assert Decimal(row["gst_collected"]) == gst > 0  # collected for the government, not revenue
    assert Decimal(row["revenue"]) == Decimal(row["commission"]) + Decimal(row["fees"]) + Decimal(
        row["subscriptions"]
    )
    assert row["trips"] == 1 and "card_fees_est" in row and report["assumptions"]

    finance = api(make_staff(Role.OPS_MANAGER))
    assert finance.get(f"/api/v1/analytics/pnl/?month={month:%Y-%m}").status_code == 200
    saved = finance.post(
        "/api/v1/analytics/pnl/",
        {"city": "chennai", "month": month.isoformat(), "revenue": "50", "promotions": "10"},
        format="json",
    )
    assert saved.status_code == 200
    budget = next(r for r in pnl.report(month)["cities"] if r["city"] == "Chennai")["budget"]
    assert budget["revenue"] == "50.00"
    assert api(make_staff(Role.FLEET_EXECUTIVE)).get("/api/v1/analytics/pnl/").status_code == 403


def test_months_are_separate():
    assert pnl.report(date(2020, 1, 1))["cities"] == []
