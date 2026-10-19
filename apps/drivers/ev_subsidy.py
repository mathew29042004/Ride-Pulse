"""EV subsidy finder for drivers thinking of switching to electric.

For the driver's state and the kind of vehicle (electric bike, auto or car) it lists the central
and state benefits that usually apply to commercial EVs, estimates each one for the vehicle's
price and battery, and shows what the vehicle loan would look like after the subsidy.

The rules change often, so amounts are **indicative**: the page says so, and support confirms the
current rules before a driver applies. Update ``SCHEMES`` when a scheme changes.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.core.exceptions import BusinessRuleViolation

VEHICLES = {
    "BIKE": "Electric scooter or bike",
    "AUTO": "Electric auto (3-wheeler)",
    "CAR": "Electric car",
}

# Each scheme: who runs it, which vehicles, and how the benefit is worked out.
SCHEMES = [
    {
        "key": "pm-e-drive",
        "name": "PM E-DRIVE (central)",
        "states": None,
        "vehicles": {"BIKE", "AUTO"},
        "per_kwh": {"BIKE": 2500, "AUTO": 2500},
        "cap": {"BIKE": 5000, "AUTO": 25000},
        "cap_pct_of_price": 15,
        "how": "Taken off the price by the dealer when you buy; the model must be on the scheme's approved list.",
    },
    {
        "key": "tn-road-tax",
        "name": "Tamil Nadu: road tax exemption",
        "states": {"Tamil Nadu"},
        "vehicles": {"BIKE", "AUTO", "CAR"},
        "pct_of_price": {"BIKE": 8, "AUTO": 8, "CAR": 10},
        "how": "No road tax when the vehicle is registered (TN EV policy).",
    },
    {
        "key": "ka-road-tax",
        "name": "Karnataka: road tax exemption",
        "states": {"Karnataka"},
        "vehicles": {"BIKE", "AUTO", "CAR"},
        "pct_of_price": {"BIKE": 10, "AUTO": 10, "CAR": 13},
        "how": "Full road tax exemption for battery EVs at registration.",
    },
    {
        "key": "kl-road-tax",
        "name": "Kerala: 50% road tax rebate",
        "states": {"Kerala"},
        "vehicles": {"BIKE", "AUTO", "CAR"},
        "pct_of_price": {"BIKE": 5, "AUTO": 5, "CAR": 10},
        "how": "Half the one-time road tax for the first registration.",
    },
    {
        "key": "kl-e-auto",
        "name": "Kerala: e-auto purchase support",
        "states": {"Kerala"},
        "vehicles": {"AUTO"},
        "flat": {"AUTO": 30000},
        "how": "For autorickshaw drivers replacing an old diesel auto, through the state's motor workers' board.",
    },
    {
        "key": "ap-road-tax",
        "name": "Andhra Pradesh: road tax and registration waiver",
        "states": {"Andhra Pradesh"},
        "vehicles": {"BIKE", "AUTO", "CAR"},
        "pct_of_price": {"BIKE": 9, "AUTO": 9, "CAR": 12},
        "how": "Road tax and registration fees waived for EVs under the AP EV policy.",
    },
]


def _round(x) -> Decimal:
    return Decimal(x).quantize(Decimal("1"), ROUND_HALF_UP)


def estimate(*, state: str, vehicle: str, price, battery_kwh) -> dict:
    if vehicle not in VEHICLES:
        raise BusinessRuleViolation("Choose an electric bike, auto or car.", field="vehicle")
    price, battery = Decimal(str(price)), Decimal(str(battery_kwh))
    if price < 30_000 or battery <= 0:
        raise BusinessRuleViolation(
            "Enter the on-road price and the battery size (kWh).", field="price"
        )
    rows = []
    for s in SCHEMES:
        if vehicle not in s["vehicles"] or (s["states"] and state not in s["states"]):
            continue
        if "per_kwh" in s:
            amount = min(
                Decimal(s["per_kwh"][vehicle]) * battery,
                Decimal(s["cap"][vehicle]),
                price * Decimal(s["cap_pct_of_price"]) / 100,
            )
        elif "pct_of_price" in s:
            amount = price * Decimal(s["pct_of_price"][vehicle]) / 100
        else:
            amount = Decimal(s["flat"][vehicle])
        rows.append(
            {
                "key": s["key"],
                "name": s["name"],
                "amount": _round(amount),
                "how": s["how"],
                "central": s["states"] is None,
            }
        )
    total = sum((r["amount"] for r in rows), Decimal(0))
    return {
        "state": state,
        "vehicle": vehicle,
        "vehicle_label": VEHICLES[vehicle],
        "price": price,
        "schemes": rows,
        "total": total,
        "net_price": max(Decimal(0), price - total),
        "indicative": True,
    }


def with_loan(driver, result: dict, *, weeks: int = 104) -> dict:
    """The vehicle loan for the price after subsidies, at the driver's rate."""
    from . import loans

    amount = (result["net_price"] // 1000) * 1000
    rate = loans.rate_for(driver)
    info = loans.eligibility(driver)
    return {
        "loan_amount": amount,
        "weeks": weeks,
        "annual_rate": rate,
        "weekly_emi": loans.emi(amount, weeks=weeks, annual_rate=rate) if amount else Decimal(0),
        "eligible": info["eligible"],
        "max_amount": info["max_amount"],
    }
