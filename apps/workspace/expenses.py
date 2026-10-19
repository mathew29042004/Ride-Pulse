"""Staff expense claims: spend on the company's behalf (fuel for a field visit, a client lunch, a
hotel on an outstation audit), claim it with the receipt, get it back in the next salary.

* **Policy**: a limit per claim for each category; claims over it are flagged, and the manager
  must give a reason to approve them anyway.
* **Receipts** are required above ₹200. Claims must be made within 60 days of spending, and the
  same amount, day and category twice is refused as a duplicate.
* **Approval** by someone above the person in the org chart (never themselves).
* **Repayment**: approved claims are added to the next payroll run as a non-taxable
  reimbursement line, and marked paid when that payroll is paid.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.core.money import ZERO, money

RECEIPT_ABOVE = Decimal(200)
CLAIM_WITHIN = timedelta(days=60)
RECEIPT_TYPES = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


class ExpenseCategory(models.TextChoices):
    FUEL = "FUEL", "Fuel and tolls"
    TRAVEL = "TRAVEL", "Train, bus or flight"
    FOOD = "FOOD", "Meals"
    STAY = "STAY", "Hotel"
    PHONE = "PHONE", "Phone and internet"
    SUPPLIES = "SUPPLIES", "Office supplies"
    OTHER = "OTHER", "Other"


POLICY = {  # most per claim (₹)
    ExpenseCategory.FUEL: Decimal(3000),
    ExpenseCategory.TRAVEL: Decimal(6000),
    ExpenseCategory.FOOD: Decimal(500),
    ExpenseCategory.STAY: Decimal(4000),
    ExpenseCategory.PHONE: Decimal(1000),
    ExpenseCategory.SUPPLIES: Decimal(2000),
    ExpenseCategory.OTHER: Decimal(1500),
}


class ClaimStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Waiting for approval"
    APPROVED = "APPROVED", "Approved · paid with salary"
    REJECTED = "REJECTED", "Not approved"
    PAID = "PAID", "Paid"


class ExpenseClaim(models.Model):
    number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="expense_claims"
    )
    category = models.CharField(max_length=8, choices=ExpenseCategory.choices)
    spent_on = models.DateField()
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    description = models.CharField(max_length=200)
    receipt = models.FileField(upload_to="expense-receipts/%Y/%m/", blank=True)
    over_policy = models.BooleanField(default=False)
    status = models.CharField(
        max_length=9, choices=ClaimStatus.choices, default=ClaimStatus.SUBMITTED
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    payslip = models.ForeignKey(
        "workspace.Payslip", null=True, blank=True, on_delete=models.SET_NULL, related_name="claims"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "workspace"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.number} ₹{self.amount}"


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def submit(
    user, *, category: str, spent_on: date, amount, description: str, receipt=None, now=None
):
    from apps.core.sequences import next_reference

    now = now or timezone.now()
    today = timezone.localdate(now)
    if not hasattr(user, "staff_profile"):
        raise ActionNotPermitted("Expense claims are for staff.")
    if category not in ExpenseCategory.values:
        raise BusinessRuleViolation("Choose a category.", field="category")
    amount = money(amount)
    if amount <= 0 or amount > 100_000:
        raise BusinessRuleViolation("Enter the amount you spent.", field="amount")
    if spent_on > today:
        raise BusinessRuleViolation("That date is in the future.", field="spent_on")
    if today - spent_on > CLAIM_WITHIN:
        raise BusinessRuleViolation(
            "Claims must be made within 60 days of spending.", field="spent_on"
        )
    if len(description.strip()) < 5:
        raise BusinessRuleViolation("Say what it was for.", field="description")
    if amount > RECEIPT_ABOVE and receipt is None:
        raise BusinessRuleViolation("Attach the receipt (needed above ₹200).", field="receipt")
    if receipt is not None and (
        _ext(receipt.name) not in RECEIPT_TYPES or receipt.size > 8 * 1024 * 1024
    ):
        raise BusinessRuleViolation("Receipts can be a photo or PDF up to 8 MB.", field="receipt")
    if (
        ExpenseClaim.objects.filter(user=user, category=category, spent_on=spent_on, amount=amount)
        .exclude(status=ClaimStatus.REJECTED)
        .exists()
    ):
        raise BusinessRuleViolation("You've already claimed this (same amount, day and category).")
    claim = ExpenseClaim.objects.create(
        number=next_reference("EXP", year=today.year),
        user=user,
        category=category,
        spent_on=spent_on,
        amount=amount,
        description=description.strip()[:200],
        receipt=receipt or "",
        over_policy=amount > POLICY[category],
        created_at=now,
    )
    manager = getattr(user.staff_profile, "reports_to", None)
    if manager is not None:
        from apps.notifications.services import notify

        notify(
            manager.user,
            f"Expense claim from {user.get_full_name()}",
            f"₹{amount:,.2f} · {claim.get_category_display()}"
            + (" · over policy" if claim.over_policy else ""),
            link="/ops/expenses",
        )
    return claim


def decide(
    claim: ExpenseClaim, *, manager, approve: bool, note: str = "", now=None
) -> ExpenseClaim:
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    from .services import team_of

    if claim.user_id == manager.pk or claim.user_id not in team_of(manager):
        raise ActionNotPermitted("Only someone above them in the team can decide this.")
    if claim.status != ClaimStatus.SUBMITTED:
        raise InvalidStateTransition("This claim has already been decided.")
    note = note.strip()
    if not approve and len(note) < 5:
        raise BusinessRuleViolation("Give a reason for not approving it.", field="note")
    if approve and claim.over_policy and len(note) < 5:
        raise BusinessRuleViolation(
            "This is over the policy limit: say why you're approving it.", field="note"
        )
    claim.status = ClaimStatus.APPROVED if approve else ClaimStatus.REJECTED
    claim.decided_by, claim.decided_at, claim.note = manager, now or timezone.now(), note[:200]
    claim.save(update_fields=["status", "decided_by", "decided_at", "note"])
    notify(
        claim.user,
        f"Expense claim {claim.number} " + ("approved" if approve else "not approved"),
        "It will be paid with your next salary." if approve else f"Reason: {note}",
        level=Level.SUCCESS if approve else Level.WARNING,
        link="/ops/expenses",
    )
    return claim


def due_for(user) -> tuple[Decimal, list[ExpenseClaim]]:
    """Approved claims not yet paid (added to the next payroll). Claims already on a draft payslip
    count again, so re-running a draft payroll keeps them."""
    claims = list(
        ExpenseClaim.objects.filter(user=user, status=ClaimStatus.APPROVED).filter(
            models.Q(payslip__isnull=True) | models.Q(payslip__status="DRAFT")
        )
    )
    return sum((c.amount for c in claims), ZERO), claims


def row(c: ExpenseClaim) -> dict:
    return {
        "id": c.pk,
        "number": c.number,
        "user_id": c.user_id,
        "name": c.user.get_full_name(),
        "category": c.category,
        "category_label": c.get_category_display(),
        "spent_on": c.spent_on,
        "amount": c.amount,
        "description": c.description,
        "has_receipt": bool(c.receipt),
        "over_policy": c.over_policy,
        "policy_limit": POLICY[c.category],
        "status": c.status,
        "status_label": c.get_status_display(),
        "note": c.note,
        "decided_by": c.decided_by.get_full_name() if c.decided_by_id else None,
        "created_at": c.created_at,
    }


DEMO_CLAIMS = [
    ("FUEL", (400, 2400), "Diesel for driver onboarding visits"),
    ("FUEL", (300, 1500), "Petrol and tolls, hub inspection"),
    ("FOOD", (120, 480), "Lunch during the vehicle audit"),
    ("TRAVEL", (450, 3200), "Bus to the regional office review"),
    ("STAY", (1800, 4800), "Hotel for the outstation fleet audit"),
    ("PHONE", (399, 999), "Mobile data for field work"),
    ("SUPPLIES", (150, 900), "Printer paper and onboarding forms"),
]


def seed_demo(*, seed: int = 71, log=print) -> dict:
    """Field staff claims over the last ~45 days: older ones approved (repaid by the payroll seed),
    recent ones waiting, a few declined with a reason."""
    import random

    from django.core.files.base import ContentFile

    from apps.accounts.models import StaffProfile

    from .services import team_of

    if ExpenseClaim.objects.exists():
        return {"expense_claims": 0}
    rng = random.Random(seed)
    now = timezone.now()
    today = timezone.localdate()
    staff = list(
        StaffProfile.objects.filter(
            user__role__in=["FLEET_EXECUTIVE", "OPS_MANAGER", "ASSOC_MAINTENANCE"]
        )
        .exclude(reports_to=None)
        .select_related("user", "reports_to__user")[:60]
    )
    made = 0
    for profile in staff:
        manager = profile.reports_to.user
        if profile.user_id not in team_of(manager):
            continue
        for _ in range(rng.randint(1, 4)):
            category, (low, high), text = rng.choice(DEMO_CLAIMS)
            spent = today - timedelta(days=rng.randint(1, 45))
            amount = Decimal(rng.randint(low, high))
            claim = ExpenseClaim(
                number=f"EXP-{spent.year}-{900000 + made:06d}",
                user=profile.user,
                category=category,
                spent_on=spent,
                amount=amount,
                description=text,
                over_policy=amount > POLICY[category],
                created_at=now - timedelta(days=(today - spent).days - 1),
            )
            if amount > RECEIPT_ABOVE:
                claim.receipt.save(
                    f"receipt-{made}.pdf", ContentFile(b"%PDF-1.4 demo receipt"), save=False
                )
            age = (today - spent).days
            if age > 10:
                declined = rng.random() < 0.08
                claim.status = ClaimStatus.REJECTED if declined else ClaimStatus.APPROVED
                claim.decided_by, claim.decided_at = manager, claim.created_at + timedelta(days=1)
                claim.note = (
                    "Personal trip, not work"
                    if declined
                    else "Festival week, only hotel near the hub"
                    if claim.over_policy
                    else ""
                )
            claim.save()
            made += 1
    log(f"  expenses: {made} claims")
    return {"expense_claims": made}
