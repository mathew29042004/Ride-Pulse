"""The fare engine. Pure functions: every rate arrives in ``FareInput``, so each fare can be unit
tested and explained to the rider line by line.

::

    metered     = base + per-km × distance + per-minute × time + paid waiting
    ride fare   = max(metered, minimum fare)
    + surge     = ride fare × (multiplier − 1)
    + fees      booking fee (+ airport fee)
    − promo     funded by the platform; never reduces the driver's earning
    + GST       5% on the taxable amount
    = total     what the rider pays

    driver earning   = (ride fare + surge) × (1 − commission)
    platform keeps   = commission + fees − promo; GST is collected for the government
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from apps.core.money import ZERO, money


@dataclass(frozen=True)
class FareCard:
    base_fare: Decimal
    per_km: Decimal
    per_minute: Decimal
    minimum_fare: Decimal
    booking_fee: Decimal = ZERO
    free_wait_minutes: Decimal = Decimal(3)
    wait_per_minute: Decimal = ZERO
    airport_fee: Decimal = ZERO


@dataclass(frozen=True)
class PromoTerms:
    code: str
    discount_type: str  # PERCENT or FLAT
    value: Decimal
    max_discount: Decimal | None = None
    min_fare: Decimal = ZERO


@dataclass(frozen=True)
class FareInput:
    card: FareCard
    distance_km: Decimal
    duration_minutes: Decimal
    surge_multiplier: Decimal = Decimal(1)
    waiting_minutes: Decimal = ZERO
    airport: bool = False
    promo: PromoTerms | None = None
    gst_rate: Decimal = Decimal("0.05")
    commission_percent: Decimal = Decimal(20)


@dataclass(frozen=True)
class FareLine:
    code: str
    label: str
    amount: Decimal
    kind: str  # FARE, SURGE, FEE, DISCOUNT, TAX


@dataclass
class FareBreakdown:
    lines: list[FareLine] = field(default_factory=list)
    distance_km: Decimal = ZERO
    duration_minutes: Decimal = ZERO
    surge_multiplier: Decimal = Decimal(1)
    ride_fare: Decimal = ZERO
    surge_amount: Decimal = ZERO
    fees: Decimal = ZERO
    discount: Decimal = ZERO
    taxable: Decimal = ZERO
    gst: Decimal = ZERO
    total: Decimal = ZERO
    driver_earning: Decimal = ZERO
    platform_commission: Decimal = ZERO
    promo_code: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = str(value)
        data["lines"] = [{**line, "amount": str(line["amount"])} for line in data["lines"]]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FareBreakdown":
        values = {
            k: (v if k == "promo_code" else Decimal(v)) for k, v in data.items() if k != "lines"
        }
        lines = [FareLine(**{**line, "amount": Decimal(line["amount"])}) for line in data["lines"]]
        return cls(lines=lines, **values)


BOOST_LABEL = "Boost (100% to your driver)"


def with_boost(fare: FareBreakdown, amount: Decimal) -> FareBreakdown:
    """Add (or change) the rider's boost: extra money to find a driver faster. It goes entirely
    to the driver, outside commission and GST (like a tip)."""
    from dataclasses import replace

    amount = Decimal(amount).quantize(Decimal("0.01"))
    previous = sum((line.amount for line in fare.lines if line.kind == "BOOST"), ZERO)
    lines = [line for line in fare.lines if line.kind != "BOOST"]
    if amount > 0:
        lines.append(FareLine("boost", BOOST_LABEL, amount, "BOOST"))
    delta = amount - previous
    return replace(
        fare, lines=lines, total=fare.total + delta, driver_earning=fare.driver_earning + delta
    )


def promo_discount(terms: PromoTerms, gross: Decimal) -> Decimal:
    if gross < terms.min_fare:
        return ZERO
    if terms.discount_type == "PERCENT":
        discount = money(gross * terms.value / 100)
    else:
        discount = money(terms.value)
    if terms.max_discount is not None:
        discount = min(discount, money(terms.max_discount))
    return min(discount, gross)


def calculate_fare(inp: FareInput) -> FareBreakdown:
    card = inp.card
    result = FareBreakdown(
        distance_km=inp.distance_km,
        duration_minutes=inp.duration_minutes,
        surge_multiplier=inp.surge_multiplier,
    )
    lines = result.lines

    base = money(card.base_fare)
    distance_charge = money(card.per_km * inp.distance_km)
    time_charge = money(card.per_minute * inp.duration_minutes)
    lines += [
        FareLine("BASE", "Base fare", base, "FARE"),
        FareLine(
            "DISTANCE", f"Distance ({inp.distance_km} km × ₹{card.per_km})", distance_charge, "FARE"
        ),
        FareLine(
            "TIME",
            f"Ride time ({inp.duration_minutes} min × ₹{card.per_minute})",
            time_charge,
            "FARE",
        ),
    ]
    metered = base + distance_charge + time_charge

    billable_wait = max(ZERO, inp.waiting_minutes - card.free_wait_minutes)
    if billable_wait > 0 and card.wait_per_minute > 0:
        waiting = money(card.wait_per_minute * billable_wait)
        metered += waiting
        lines.append(FareLine("WAITING", f"Waiting ({billable_wait} min)", waiting, "FARE"))

    ride_fare = max(metered, money(card.minimum_fare))
    if ride_fare > metered:
        lines.append(FareLine("MINIMUM", "Minimum fare adjustment", ride_fare - metered, "FARE"))

    surge_amount = ZERO
    if inp.surge_multiplier > 1:
        surge_amount = money(ride_fare * (inp.surge_multiplier - 1))
        lines.append(FareLine("SURGE", f"Surge {inp.surge_multiplier}×", surge_amount, "SURGE"))

    fees = money(card.booking_fee)
    if fees:
        lines.append(FareLine("BOOKING_FEE", "Booking fee", fees, "FEE"))
    if inp.airport and card.airport_fee:
        fees += money(card.airport_fee)
        lines.append(FareLine("AIRPORT_FEE", "Airport access fee", money(card.airport_fee), "FEE"))

    gross = ride_fare + surge_amount + fees
    discount = promo_discount(inp.promo, gross) if inp.promo else ZERO
    if discount:
        lines.append(FareLine("PROMO", f"Promo {inp.promo.code}", -discount, "DISCOUNT"))
        result.promo_code = inp.promo.code

    taxable = gross - discount
    gst = money(taxable * inp.gst_rate)
    lines.append(FareLine("GST", f"GST {inp.gst_rate * 100:.0f}%", gst, "TAX"))

    commission = money((ride_fare + surge_amount) * inp.commission_percent / 100)
    result.ride_fare = ride_fare
    result.surge_amount = surge_amount
    result.fees = fees
    result.discount = discount
    result.taxable = taxable
    result.gst = gst
    result.total = taxable + gst
    result.platform_commission = commission
    result.driver_earning = ride_fare + surge_amount - commission
    return result
