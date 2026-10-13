from decimal import Decimal

import pytest

from apps.core.money import format_inr, money, split_amount
from apps.pricing.fare import FareCard, FareInput, PromoTerms, calculate_fare, promo_discount

CARD = FareCard(
    base_fare=Decimal(50),
    per_km=Decimal(12),
    per_minute=Decimal("1.5"),
    minimum_fare=Decimal(80),
    booking_fee=Decimal(12),
    free_wait_minutes=Decimal(3),
    wait_per_minute=Decimal(2),
    airport_fee=Decimal(100),
)


def fare(**overrides):
    params = {
        "card": CARD,
        "distance_km": Decimal("6.66"),
        "duration_minutes": Decimal("17.38"),
        **overrides,
    }
    return calculate_fare(FareInput(**params))


def test_metered_fare_matches_hand_calculation():
    f = fare()
    assert f.ride_fare == Decimal("155.99")  # 50 + 79.92 + 26.07
    assert f.fees == Decimal("12.00")
    assert f.gst == Decimal("8.40")  # 5% of 167.99
    assert f.total == Decimal("176.39")
    assert f.platform_commission == Decimal("31.20")  # 20% of the ride fare
    assert f.driver_earning == Decimal("124.79")


def test_parts_always_add_up_to_the_total():
    for km in ("0.5", "3.2", "11.7", "42"):
        for surge in ("1", "1.4", "2.5"):
            f = fare(
                distance_km=Decimal(km),
                surge_multiplier=Decimal(surge),
                promo=PromoTerms("X", "PERCENT", Decimal(20), Decimal(60)),
            )
            assert f.driver_earning + f.platform_commission + f.fees - f.discount + f.gst == f.total


def test_minimum_fare_applies_to_short_trips():
    f = fare(distance_km=Decimal("0.8"), duration_minutes=Decimal(3))
    assert f.ride_fare == Decimal("80.00")
    assert any(line.code == "MINIMUM" for line in f.lines)


def test_surge_multiplies_the_ride_fare_not_the_fees():
    base = fare()
    surged = fare(surge_multiplier=Decimal("1.5"))
    assert surged.surge_amount == money(base.ride_fare * Decimal("0.5"))
    assert surged.fees == base.fees


def test_waiting_is_charged_only_after_the_free_minutes():
    assert fare(waiting_minutes=Decimal(2)).total == fare().total
    longer = fare(waiting_minutes=Decimal(7))
    assert any(line.code == "WAITING" and line.amount == Decimal("8.00") for line in longer.lines)


def test_airport_fee_only_for_airport_trips():
    assert fare(airport=True).fees == Decimal("112.00")


def test_promo_is_capped_and_funded_by_the_platform():
    plain = fare()
    discounted = fare(promo=PromoTerms("RIDE20", "PERCENT", Decimal(20), max_discount=Decimal(25)))
    assert discounted.discount == Decimal("25.00")
    assert discounted.driver_earning == plain.driver_earning


def test_promo_respects_minimum_fare():
    terms = PromoTerms("BIG", "FLAT", Decimal(100), min_fare=Decimal(500))
    assert promo_discount(terms, Decimal(300)) == 0
    assert promo_discount(terms, Decimal(600)) == Decimal("100.00")


def test_promo_never_exceeds_the_fare():
    assert promo_discount(PromoTerms("FREE", "FLAT", Decimal(1000)), Decimal(120)) == Decimal(120)


def test_breakdown_round_trips_through_json():
    f = fare(surge_multiplier=Decimal("1.3"), promo=PromoTerms("X", "FLAT", Decimal(10)))
    from apps.pricing.fare import FareBreakdown

    assert FareBreakdown.from_dict(f.to_dict()) == f


@pytest.mark.parametrize(
    ("total", "parts", "expected"),
    [
        ("100", 3, ["33.34", "33.33", "33.33"]),
        ("10", 4, ["2.50"] * 4),
        ("0.05", 2, ["0.03", "0.02"]),
    ],
)
def test_split_amount_is_exact(total, parts, expected):
    result = split_amount(Decimal(total), parts)
    assert [str(x) for x in result] == expected
    assert sum(result) == Decimal(total)


def test_indian_digit_grouping():
    assert format_inr(Decimal("1234567.5")) == "₹12,34,567.50"
    assert format_inr(999) == "₹999.00"
    assert format_inr(-1500) == "-₹1,500.00"
