"""Fuel prices and fare revisions: when petrol, diesel or CNG prices change in a state, see what
it does to drivers' running costs and get a suggested per-km fare for each ride type.

* Ops record fuel prices per state as they change (one row per change).
* For each ride type the main fuel and typical mileage give the fuel cost per km; the change in
  that cost since the price the fares were last set at is the suggested change to ``per_km``
  (passed through in full, rounded to 25 paise), so drivers' margins stay where they were.
* The page also shows what a typical driver loses per day if fares aren't revised (cost change
  × the average km a driver drives a day in that state).
* Applying a suggestion updates every active fare rule for that ride type in the state, records
  the fuel price it was based on, and is written to the audit log.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

# ride type: (fuel, km per unit). CNG per kg, petrol and diesel per litre.
MILEAGE = {
    "BIKE": ("PETROL", Decimal(45)),
    "AUTO": ("CNG", Decimal(30)),
    "MINI": ("CNG", Decimal(24)),
    "SHARE": ("CNG", Decimal(24)),
    "SEDAN": ("PETROL", Decimal(15)),
    "SUV": ("DIESEL", Decimal(12)),
}


class Fuel(models.TextChoices):
    PETROL = "PETROL", "Petrol (₹/litre)"
    DIESEL = "DIESEL", "Diesel (₹/litre)"
    CNG = "CNG", "CNG (₹/kg)"


class FuelPrice(models.Model):
    state = models.CharField(max_length=60)
    fuel = models.CharField(max_length=6, choices=Fuel.choices)
    price = models.DecimalField(max_digits=7, decimal_places=2)
    effective_on = models.DateField()
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        app_label = "pricing"
        ordering = ["-effective_on", "-pk"]

    def __str__(self) -> str:
        return f"{self.state} {self.fuel} ₹{self.price}"


class FareFuelBasis(models.Model):
    """The fuel price a state's per-km fares for a ride type were last set at."""

    state = models.CharField(max_length=60)
    ride_type = models.ForeignKey("pricing.RideType", on_delete=models.CASCADE, related_name="+")
    price = models.DecimalField(max_digits=7, decimal_places=2)
    set_on = models.DateField()

    class Meta:
        app_label = "pricing"
        constraints = [
            models.UniqueConstraint(fields=["state", "ride_type"], name="fuel_basis_once")
        ]

    def __str__(self) -> str:
        return f"{self.state} {self.ride_type_id} at ₹{self.price}"


def record(*, state: str, fuel: str, price, user, effective_on=None) -> FuelPrice:
    if fuel not in Fuel.values:
        raise BusinessRuleViolation("Choose petrol, diesel or CNG.", field="fuel")
    price = Decimal(str(price))
    if not Decimal(30) <= price <= Decimal(200):
        raise BusinessRuleViolation("That doesn't look like a fuel price (₹30–200).", field="price")
    return FuelPrice.objects.create(
        state=state,
        fuel=fuel,
        price=price,
        effective_on=effective_on or timezone.localdate(),
        entered_by=user,
    )


def latest(state: str, fuel: str) -> FuelPrice | None:
    return FuelPrice.objects.filter(state=state, fuel=fuel).first()


def _km_per_driver_day(state: str) -> Decimal:
    from django.db.models import Count, Sum

    from apps.rides.models import Trip

    since = timezone.now() - timedelta(days=28)
    agg = Trip.objects.filter(
        city__state=state, status="COMPLETED", completed_at__gte=since
    ).aggregate(km=Sum("actual_distance_km"), drivers=Count("driver", distinct=True))
    if not agg["drivers"]:
        return Decimal(120)
    # Paid km plus about 40% driven empty to pickups, per driver per working day (~24 in 28).
    return (Decimal(agg["km"] or 0) * Decimal("1.4") / agg["drivers"] / 24).quantize(Decimal("1"))


def _quarter(x: Decimal) -> Decimal:
    return (x * 4).quantize(Decimal("1"), ROUND_HALF_UP) / 4


def suggestions(state: str) -> dict:
    from .models import FareRule

    km_day = _km_per_driver_day(state)
    rows = []
    for rule_type in (
        FareRule.objects.filter(city__state=state, is_active=True)
        .values_list("ride_type__code", "ride_type_id", "ride_type__name")
        .distinct()
    ):
        code, type_id, name = rule_type
        if code not in MILEAGE:
            continue
        fuel, mileage = MILEAGE[code]
        now_price = latest(state, fuel)
        if now_price is None:
            continue
        basis = FareFuelBasis.objects.filter(state=state, ride_type_id=type_id).first()
        old = basis.price if basis else now_price.price
        change = (now_price.price - old) / mileage
        per_km = FareRule.objects.filter(
            city__state=state, ride_type_id=type_id, is_active=True
        ).values_list("per_km", flat=True)
        rates = list(per_km)
        avg = sum(rates, Decimal(0)) / len(rates) if rates else Decimal(0)
        rows.append(
            {
                "ride_type": code,
                "ride_type_id": type_id,
                "name": name,
                "fuel": fuel,
                "mileage": mileage,
                "basis_price": old,
                "current_price": now_price.price,
                "cost_per_km_change": change.quantize(Decimal("0.01")),
                "suggested_change": _quarter(change),
                "current_per_km": avg.quantize(Decimal("0.01")),
                "driver_loss_per_day": (change * km_day).quantize(Decimal("1"))
                if change > 0
                else Decimal(0),
                "cities": len(rates),
            }
        )
    return {"state": state, "km_per_driver_day": km_day, "rows": rows}


@transaction.atomic
def apply(state: str, ride_type, *, user) -> int:
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    from .models import FareRule

    row = next((r for r in suggestions(state)["rows"] if r["ride_type_id"] == ride_type.pk), None)
    if row is None:
        raise BusinessRuleViolation(
            "No fuel price recorded for this ride type's fuel in the state."
        )
    change = row["suggested_change"]
    rules = list(FareRule.objects.filter(city__state=state, ride_type=ride_type, is_active=True))
    for rule in rules:
        new = max(Decimal("1.00"), rule.per_km + change)
        log_event(
            AuditAction.UPDATE,
            rule,
            message=f"Fuel revision: {row['fuel']} ₹{row['basis_price']} → ₹{row['current_price']}",
            changes={"per_km": [str(rule.per_km), str(new)]},
            actor=user,
        )
        rule.per_km = new
        rule.save(update_fields=["per_km", "updated_at"])
    FareFuelBasis.objects.update_or_create(
        state=state,
        ride_type=ride_type,
        defaults={"price": row["current_price"], "set_on": timezone.localdate()},
    )
    return len(rules)


# Approximate prices per state (₹): fares were set at the first, today's is the second.
DEMO_PRICES = {
    "Tamil Nadu": {"PETROL": (100.8, 101.2), "DIESEL": (92.4, 92.9), "CNG": (84.0, 89.5)},
    "Karnataka": {"PETROL": (102.9, 103.3), "DIESEL": (88.9, 89.3), "CNG": (85.5, 88.0)},
    "Kerala": {"PETROL": (107.6, 107.9), "DIESEL": (96.5, 96.8), "CNG": (86.0, 91.0)},
    "Andhra Pradesh": {"PETROL": (109.1, 109.6), "DIESEL": (97.0, 97.4), "CNG": (90.0, 93.5)},
}


def seed_demo(*, log=print) -> dict:
    from datetime import timedelta

    from .models import RideType

    if FuelPrice.objects.exists():
        return {"fuel_prices": 0}
    today = timezone.localdate()
    made = 0
    for state, fuels in DEMO_PRICES.items():
        for fuel, (old, new) in fuels.items():
            FuelPrice.objects.create(
                state=state,
                fuel=fuel,
                price=Decimal(str(old)),
                effective_on=today - timedelta(days=120),
            )
            FuelPrice.objects.create(
                state=state,
                fuel=fuel,
                price=Decimal(str(new)),
                effective_on=today - timedelta(days=6),
            )
            made += 2
        for code, (fuel, _) in MILEAGE.items():
            ride_type = RideType.objects.filter(code=code).first()
            if ride_type:
                FareFuelBasis.objects.update_or_create(
                    state=state,
                    ride_type=ride_type,
                    defaults={
                        "price": Decimal(str(fuels[fuel][0])),
                        "set_on": today - timedelta(days=120),
                    },
                )
    log(f"  fuel prices: {made}")
    return {"fuel_prices": made}
