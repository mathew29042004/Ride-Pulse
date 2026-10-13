"""Money helpers. All amounts are ``Decimal`` rupees rounded half-up to paise."""

from decimal import ROUND_HALF_UP, Decimal

PAISA = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def whole_rupees(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(RUPEE, rounding=ROUND_HALF_UP)


def percent_of(amount: Decimal, percent: Decimal | int | str) -> Decimal:
    return money(Decimal(amount) * Decimal(str(percent)) / Decimal(100))


def split_amount(total: Decimal, parts: int) -> list[Decimal]:
    """Split ``total`` into ``parts`` installments that add up exactly.

    Leftover paise go to the earliest installments, so 100.00 / 3 -> [33.34, 33.33, 33.33].
    """
    if parts < 1:
        raise ValueError("parts must be at least 1")
    total_paise = int(money(total) / PAISA)
    base, remainder = divmod(total_paise, parts)
    return [money(Decimal(base + (1 if i < remainder else 0)) * PAISA) for i in range(parts)]


def format_inr(value: Decimal | int | float | str | None, *, symbol: str = "₹") -> str:
    """Format with Indian digit grouping: 1234567.5 -> ₹12,34,567.50."""
    if value is None or value == "":
        return "—"
    amount = money(value)
    sign = "-" if amount < 0 else ""
    rupees, paise = f"{abs(amount):.2f}".split(".")
    if len(rupees) > 3:
        head, tail = rupees[:-3], rupees[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        rupees = ",".join([*groups, tail])
    return f"{sign}{symbol}{rupees}.{paise}"
