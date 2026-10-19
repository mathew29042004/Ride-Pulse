"""Vehicle loans for drivers, through a partner NBFC.

A driver applies in the app for a loan to buy or upgrade a vehicle; ops approve it and the partner
pays the dealer directly (that money never passes through Ride Pulse). The weekly EMI is then
deducted from the driver's earnings just before the weekly payout, and passed on to the partner.

Drivers always keep a minimum: at most half the week's balance goes to the EMI, and never so much
that less than ``KEEP_AT_LEAST`` is left. Anything short carries to next week as arrears, with no
penalty. Loans can be paid off early with no fee.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.core.money import ZERO, money
from apps.payments.accounts import LOAN_PARTNER as PARTNER

PARTNER_NAME = "Shakti Finance (partner NBFC)"
ANNUAL_RATE = Decimal("14.0")  # % a year, reducing balance
TENURES = (52, 104, 156)  # weeks
MAX_PRINCIPAL = Decimal(600_000)
EMI_SHARE_MAX = Decimal("0.5")  # at most half the week's balance
KEEP_AT_LEAST = Decimal(1500)
MIN_TRIPS = 200
MIN_DAYS = 90
MIN_RATING = Decimal("4.5")


class LoanStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Applied"
    ACTIVE = "ACTIVE", "Repaying"
    REJECTED = "REJECTED", "Not approved"
    CLOSED = "CLOSED", "Paid off"


class VehicleLoan(models.Model):
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="loans"
    )
    vehicle = models.CharField(max_length=80)  # what they're buying, e.g. "Tata Tiago EV 2026"
    principal = models.DecimalField(max_digits=10, decimal_places=2)
    annual_rate = models.DecimalField(max_digits=4, decimal_places=2, default=ANNUAL_RATE)
    tenure_weeks = models.PositiveSmallIntegerField()
    weekly_emi = models.DecimalField(max_digits=9, decimal_places=2)
    outstanding = models.DecimalField(max_digits=10, decimal_places=2)
    arrears = models.DecimalField(max_digits=9, decimal_places=2, default=ZERO)
    status = models.CharField(
        max_length=10, choices=LoanStatus.choices, default=LoanStatus.REQUESTED
    )
    note = models.CharField(max_length=200, blank=True)
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "drivers"
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"Loan {self.pk} {self.driver_id} ₹{self.principal}"


class LoanRepayment(models.Model):
    loan = models.ForeignKey(VehicleLoan, on_delete=models.CASCADE, related_name="repayments")
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    interest = models.DecimalField(max_digits=9, decimal_places=2)
    principal = models.DecimalField(max_digits=9, decimal_places=2)
    due = models.DecimalField(max_digits=9, decimal_places=2)  # EMI plus any arrears that week
    early = models.BooleanField(default=False)
    at = models.DateTimeField()

    class Meta:
        app_label = "drivers"
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"₹{self.amount} on loan {self.loan_id}"


def emi(principal: Decimal, *, weeks: int, annual_rate: Decimal = ANNUAL_RATE) -> Decimal:
    """Standard reducing-balance EMI with weekly compounding."""
    r = annual_rate / Decimal(100) / Decimal(52)
    if r == 0:
        return money(principal / weeks)
    factor = (1 + r) ** weeks
    return (principal * r * factor / (factor - 1)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _weekly_interest(loan: VehicleLoan) -> Decimal:
    return money(loan.outstanding * loan.annual_rate / Decimal(100) / Decimal(52))


def average_weekly_earnings(driver, *, weeks: int = 8, now=None) -> Decimal:
    from apps.payments.services import driver_earnings

    now = now or timezone.now()
    total = driver_earnings(driver, start=now - timedelta(weeks=weeks), end=now)["earnings"]
    return money(total / weeks)


def eligibility(driver, *, now=None) -> dict:
    """Whether the driver can apply, the most they can borrow, and why not if they can't."""
    now = now or timezone.now()
    reasons = []
    if driver.completed_trips < MIN_TRIPS:
        reasons.append(f"Complete {MIN_TRIPS} trips (you have {driver.completed_trips}).")
    if not driver.approved_at or driver.approved_at > now - timedelta(days=MIN_DAYS):
        reasons.append(f"Drive with us for {MIN_DAYS} days.")
    if driver.rating < MIN_RATING:
        reasons.append(f"Keep a rating of {MIN_RATING} or more.")
    if driver.loans.filter(status__in=[LoanStatus.REQUESTED, LoanStatus.ACTIVE]).exists():
        reasons.append("You already have a loan or an application.")
    weekly = average_weekly_earnings(driver, now=now)
    # The longest tenure's EMI must fit in 30% of a normal week's earnings.
    r = ANNUAL_RATE / 100 / 52
    weeks = TENURES[-1]
    factor = (1 + r) ** weeks
    affordable = weekly * Decimal("0.3") * (factor - 1) / (r * factor) if weekly > 0 else ZERO
    limit = min(MAX_PRINCIPAL, (affordable // 1000) * 1000)
    if limit < 20_000 and not reasons:
        reasons.append("Your recent weekly earnings are too low for a loan right now.")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "max_amount": limit,
        "weekly_earnings": weekly,
        "annual_rate": ANNUAL_RATE,
        "tenures": list(TENURES),
        "partner": PARTNER_NAME,
        "keep_at_least": KEEP_AT_LEAST,
    }


def apply(driver, *, vehicle: str, amount: Decimal, weeks: int, now=None) -> VehicleLoan:
    now = now or timezone.now()
    info = eligibility(driver, now=now)
    if not info["eligible"]:
        raise BusinessRuleViolation(info["reasons"][0])
    if weeks not in TENURES:
        raise BusinessRuleViolation("Choose 1, 2 or 3 years.", field="weeks")
    amount = money(amount)
    if amount < 20_000 or amount > info["max_amount"]:
        raise BusinessRuleViolation(
            f"You can borrow between ₹20,000 and ₹{info['max_amount']:,.0f}.", field="amount"
        )
    vehicle = vehicle.strip()[:80]
    if len(vehicle) < 3:
        raise BusinessRuleViolation("Tell us which vehicle you're buying.", field="vehicle")
    return VehicleLoan.objects.create(
        driver=driver,
        vehicle=vehicle,
        principal=amount,
        tenure_weeks=weeks,
        weekly_emi=emi(amount, weeks=weeks),
        outstanding=amount,
        requested_at=now,
    )


def decide(loan: VehicleLoan, *, approve: bool, user, note: str = "", now=None) -> VehicleLoan:
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    if loan.status != LoanStatus.REQUESTED:
        raise BusinessRuleViolation("This application has already been decided.")
    loan.status = LoanStatus.ACTIVE if approve else LoanStatus.REJECTED
    loan.decided_at, loan.decided_by, loan.note = now or timezone.now(), user, note[:200]
    loan.save(update_fields=["status", "decided_at", "decided_by", "note"])
    if approve:
        notify(
            loan.driver.user,
            "Your vehicle loan is approved",
            f"₹{loan.principal:,.0f} goes to the dealer from {PARTNER_NAME}. Your EMI of "
            f"₹{loan.weekly_emi} comes out of your weekly earnings; you always keep at least "
            f"₹{KEEP_AT_LEAST:,.0f}.",
            level=Level.SUCCESS,
            link="/drive/loan",
        )
    else:
        notify(
            loan.driver.user,
            "Your loan application",
            note or "We couldn't approve it this time.",
            link="/drive/loan",
        )
    return loan


def _record(loan: VehicleLoan, wallet, amount: Decimal, *, due: Decimal, early: bool, now) -> None:
    from apps.payments.models import TransactionKind
    from apps.payments.services import post

    interest = min(amount, _weekly_interest(loan)) if not early else ZERO
    principal = min(amount - interest, loan.outstanding)
    amount = interest + principal
    if amount <= 0:
        return
    post(
        TransactionKind.LOAN_EMI,
        [(wallet, -amount), (PARTNER, amount)],
        description=f"Vehicle loan EMI ({loan.vehicle})",
        at=now,
    )
    LoanRepayment.objects.create(
        loan=loan,
        amount=amount,
        interest=interest,
        principal=principal,
        due=due,
        early=early,
        at=now,
    )
    loan.outstanding -= principal
    if loan.outstanding <= 0:
        loan.outstanding, loan.arrears = ZERO, ZERO
        loan.status, loan.closed_at = LoanStatus.CLOSED, now
    loan.save(update_fields=["outstanding", "arrears", "status", "closed_at"])


def collect(*, now: datetime | None = None) -> dict:
    """Run just before weekly payouts: take each active loan's EMI (plus arrears) from earnings."""
    from apps.payments.models import Wallet

    now = now or timezone.now()
    collected, short = ZERO, 0
    for loan in VehicleLoan.objects.filter(status=LoanStatus.ACTIVE).select_related("driver__user"):
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().filter(user=loan.driver.user).first()
            balance = wallet.balance if wallet else ZERO
            due = min(loan.weekly_emi + loan.arrears, loan.outstanding + _weekly_interest(loan))
            room = max(ZERO, min(money(balance * EMI_SHARE_MAX), balance - KEEP_AT_LEAST))
            take = min(due, room)
            loan.arrears = money(due - take) if due - take > 0 else ZERO
            if take > 0:
                _record(loan, wallet, take, due=due, early=False, now=now)
                collected += take
            else:
                loan.save(update_fields=["arrears"])
            short += take < due
    return {"collected": collected, "short": short}


def pay_off(loan: VehicleLoan, *, now=None) -> VehicleLoan:
    """Pay the rest of the loan early from the wallet; no fee."""
    from apps.payments.models import Wallet

    now = now or timezone.now()
    if loan.status != LoanStatus.ACTIVE:
        raise BusinessRuleViolation("Only an active loan can be paid off.")
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(user=loan.driver.user)
        if wallet.balance < loan.outstanding:
            raise BusinessRuleViolation(
                f"You need ₹{loan.outstanding:,.2f} in your earnings balance to pay it off."
            )
        _record(loan, wallet, loan.outstanding, due=loan.outstanding, early=True, now=now)
    loan.refresh_from_db()
    return loan


def row(loan: VehicleLoan) -> dict:
    paid = sum((r.amount for r in loan.repayments.all()), ZERO)
    return {
        "id": loan.pk,
        "driver": loan.driver.name,
        "driver_id": loan.driver_id,
        "city": loan.driver.city.name if loan.driver.city_id else "",
        "vehicle": loan.vehicle,
        "principal": loan.principal,
        "annual_rate": loan.annual_rate,
        "tenure_weeks": loan.tenure_weeks,
        "weekly_emi": loan.weekly_emi,
        "outstanding": loan.outstanding,
        "arrears": loan.arrears,
        "paid": paid,
        "status": loan.status,
        "status_label": loan.get_status_display(),
        "note": loan.note,
        "requested_at": loan.requested_at,
        "repayments": [
            {
                "amount": r.amount,
                "interest": r.interest,
                "principal": r.principal,
                "due": r.due,
                "early": r.early,
                "at": r.at,
            }
            for r in loan.repayments.all()[:20]
        ],
    }


def seed_demo(*, seed: int = 31, log=print) -> dict:
    """Experienced drivers with loans part-repaid (history only, before the demo's ledger), and a
    few applications waiting for ops."""
    import random

    from .models import DriverProfile

    if VehicleLoan.objects.exists():
        return {"loans": 0}
    rng = random.Random(seed)
    now = timezone.now()
    drivers = list(
        DriverProfile.objects.filter(completed_trips__gt=0).order_by("-completed_trips")[
            :30
        ]
    )
    vehicles = [
        "Tata Tiago EV",
        "Maruti Dzire CNG",
        "Bajaj RE Compact (auto)",
        "Hyundai Aura CNG",
        "Mahindra e-Alfa (e-auto)",
        "Toyota Innova Crysta",
        "TVS iQube (bike)",
    ]
    made = 0
    for i, driver in enumerate(drivers):
        principal = Decimal(rng.choice([60_000, 120_000, 250_000, 400_000, 550_000]))
        weeks = rng.choice(TENURES)
        loan = VehicleLoan(
            driver=driver,
            vehicle=rng.choice(vehicles),
            principal=principal,
            tenure_weeks=weeks,
            weekly_emi=emi(principal, weeks=weeks),
            outstanding=principal,
        )
        if i < 6:
            loan.requested_at = now - timedelta(hours=rng.randint(2, 70))
            loan.save()
            made += 1
            continue
        paid_weeks = rng.randint(3, 40)
        loan.status = LoanStatus.ACTIVE
        loan.requested_at = loan.decided_at = now - timedelta(weeks=paid_weeks, days=3)
        loan.save()
        repayments = []
        for w in range(paid_weeks):
            interest = _weekly_interest(loan)
            short = rng.random() < 0.08
            amount = money(loan.weekly_emi * (Decimal("0.4") if short else 1))
            part = min(amount - min(amount, interest), loan.outstanding)
            loan.outstanding -= part
            if short and w == paid_weeks - 1:
                loan.arrears = loan.weekly_emi - amount
            repayments.append(
                LoanRepayment(
                    loan=loan,
                    amount=min(amount, interest) + part,
                    interest=min(amount, interest),
                    principal=part,
                    due=loan.weekly_emi,
                    at=now - timedelta(weeks=paid_weeks - w),
                )
            )
        LoanRepayment.objects.bulk_create(repayments)
        loan.save(update_fields=["outstanding", "arrears"])
        made += 1
    log(f"  vehicle loans: {made}")
    return {"loans": made}
