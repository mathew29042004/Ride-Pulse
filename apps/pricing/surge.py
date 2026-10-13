"""Dynamic (surge) pricing.

Each zone's multiplier responds to the ratio of open demand (ride requests in the last few
minutes) to free supply (online drivers in the zone). Two safeguards keep prices sane:

* exponential smoothing, so the price doesn't flicker with every request, and
* a hard cap (3.0× by default) plus 0.1× steps that riders can understand.
"""

from decimal import ROUND_HALF_UP, Decimal

ONE = Decimal(1)
STEP = Decimal("0.1")
ELASTICITY = Decimal("0.6")  # each unit of excess demand ratio adds 0.6× to the price


def raw_multiplier(demand: int, supply: int, *, cap: Decimal) -> Decimal:
    if demand <= 0:
        return ONE
    ratio = Decimal(demand) / Decimal(max(supply, 0.5))
    if ratio <= 1:
        return ONE
    return min(ONE + (ratio - 1) * ELASTICITY, cap)


def smooth(previous: Decimal, target: Decimal, alpha: Decimal) -> Decimal:
    return previous + (target - previous) * alpha


def to_step(value: Decimal, *, cap: Decimal) -> Decimal:
    stepped = (value / STEP).quantize(ONE, rounding=ROUND_HALF_UP) * STEP
    return max(ONE, min(stepped, cap)).quantize(STEP)


def next_multiplier(
    *, previous: Decimal, demand: int, supply: int, cap: Decimal, alpha: Decimal
) -> Decimal:
    target = raw_multiplier(demand, supply, cap=cap)
    return to_step(smooth(previous, target, alpha), cap=cap)
