"""India's Motor Vehicle Aggregator Guidelines, 2025 (central guidelines; each state notifies its
own rules and may change these numbers), as Ride Pulse applies them.

The defaults below follow the 2025 central guidelines as we understand them. **Check them against
your state's notified rules** and override per state in ``settings.AGGREGATOR_RULES``.
"""

from decimal import Decimal

from django.conf import settings

DEFAULTS = {
    # Pricing
    "surge_cap": Decimal("2.0"),  # at most 2x the base fare
    "driver_share_min_percent": Decimal("80"),  # drivers who own their vehicle keep >= 80%
    "cancellation_fee_percent": Decimal("10"),  # of the fare...
    "cancellation_fee_max": Decimal("100"),  # ...and never more than ₹100
    # Drivers
    "police_verification": True,  # before the first ride
    "induction_training": True,  # before the first ride, with a yearly refresher
    "refresher_months": 12,
    "health_cover": 500_000,  # ₹ per driver
    "term_cover": 1_000_000,  # ₹ per driver
    # Vehicles
    "vehicle_max_age_years": 8,
}


def for_state(state: str | None) -> dict:
    overrides = getattr(settings, "AGGREGATOR_RULES", {}).get(state or "", {})
    return {**DEFAULTS, **overrides}


def surge_cap(state: str | None) -> Decimal:
    return Decimal(str(for_state(state)["surge_cap"]))


def cap_cancellation_fee(fee: Decimal, fare: Decimal | None, state: str | None) -> Decimal:
    """A cancellation fee is at most the state's share of the fare and its rupee maximum."""
    rules = for_state(state)
    limit = Decimal(str(rules["cancellation_fee_max"]))
    if fare:
        limit = min(limit, (Decimal(fare) * Decimal(str(rules["cancellation_fee_percent"])) / 100))
    return max(Decimal(0), min(Decimal(fee), limit)).quantize(Decimal("0.01"))
