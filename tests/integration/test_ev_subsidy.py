"""EV subsidy finder: the right schemes per state and vehicle, caps applied, loan after subsidy."""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import ev_subsidy

pytestmark = pytest.mark.django_db


def test_schemes_by_state_and_vehicle():
    tn_auto = ev_subsidy.estimate(state="Tamil Nadu", vehicle="AUTO", price=350_000, battery_kwh=8)
    names = {s["key"] for s in tn_auto["schemes"]}
    assert names == {"pm-e-drive", "tn-road-tax"}
    pm = next(s for s in tn_auto["schemes"] if s["key"] == "pm-e-drive")
    assert pm["amount"] == Decimal(20_000)  # 8 kWh × ₹2,500, under the ₹25,000 cap
    kl_auto = ev_subsidy.estimate(state="Kerala", vehicle="AUTO", price=350_000, battery_kwh=12)
    assert "kl-e-auto" in {s["key"] for s in kl_auto["schemes"]}
    assert next(s for s in kl_auto["schemes"] if s["key"] == "pm-e-drive")["amount"] == Decimal(
        25_000
    )  # capped
    car = ev_subsidy.estimate(state="Karnataka", vehicle="CAR", price=1_200_000, battery_kwh=26)
    assert {s["key"] for s in car["schemes"]} == {"ka-road-tax"}  # PM E-DRIVE doesn't cover cars
    assert car["net_price"] == car["price"] - car["total"]
    with pytest.raises(BusinessRuleViolation):
        ev_subsidy.estimate(state="Kerala", vehicle="TRUCK", price=1, battery_kwh=1)


def test_api_with_loan(api, make_driver):
    driver = make_driver(online=False)
    r = (
        api(driver.user)
        .get("/api/v1/driver/ev-subsidy/?vehicle=AUTO&price=350000&battery_kwh=8")
        .json()
    )
    assert r["indicative"] and r["total"] > 0 and r["loan"]["loan_amount"] <= float(r["net_price"])
