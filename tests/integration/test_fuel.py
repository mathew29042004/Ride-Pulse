"""Fuel price changes → suggested per-km fare changes, applied with an audit trail."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.core.exceptions import BusinessRuleViolation
from apps.pricing import fuel
from apps.pricing.models import FareRule, RideType

pytestmark = pytest.mark.django_db


def test_cng_rise_suggests_and_applies(api, admin):
    with pytest.raises(BusinessRuleViolation):
        fuel.record(state="Tamil Nadu", fuel="CNG", price=5, user=admin)
    mini = RideType.objects.get(code="MINI")
    fuel.record(state="Tamil Nadu", fuel="CNG", price=Decimal(80), user=admin)
    fuel.apply("Tamil Nadu", mini, user=admin)  # sets the basis at ₹80
    before = list(
        FareRule.objects.filter(city__state="Tamil Nadu", ride_type=mini).values_list(
            "pk", "per_km"
        )
    )
    fuel.record(state="Tamil Nadu", fuel="CNG", price=Decimal(92), user=admin)
    row = next(r for r in fuel.suggestions("Tamil Nadu")["rows"] if r["ride_type"] == "MINI")
    assert row["cost_per_km_change"] == Decimal("0.50")  # ₹12 / 24 km per kg
    assert row["suggested_change"] == Decimal("0.50") and row["driver_loss_per_day"] > 0
    updated = (
        api(admin)
        .post(
            "/api/v1/ops/fuel/apply/", {"state": "Tamil Nadu", "ride_type": "MINI"}, format="json"
        )
        .json()
    )
    assert updated["updated"] == len(before)
    for pk, old in before:
        assert FareRule.objects.get(pk=pk).per_km == old + Decimal("0.50")
    assert AuditLog.objects.filter(message__startswith="Fuel revision").count() >= len(before)
    # Once applied, the suggestion goes back to zero.
    row = next(r for r in fuel.suggestions("Tamil Nadu")["rows"] if r["ride_type"] == "MINI")
    assert row["suggested_change"] == 0
