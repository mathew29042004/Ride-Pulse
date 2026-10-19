"""Payroll: monthly salaries for staff, worked out from attendance and leave, with India's
statutory deductions, approved by HR and paid by bank transfer. Every employee sees and downloads
their own payslips.

* **Salary structure** (per person): monthly gross split into basic (50%), HRA (50% of basic in a
  metro city, 40% elsewhere) and a special allowance (the rest).
* **Loss of pay**: each absent day (no clock-in on a rostered day, no approved leave) costs one
  day's gross; a half day costs half. Approved leave is paid.
* **Overtime**: time worked beyond the shift (30 minutes or more on a day) at twice the hourly
  basic rate. **Night allowance**: ₹200 for each night shift worked.
* **Deductions**: PF 12% of basic (basic capped at ₹15,000 for PF, so at most ₹1,800); ESI 0.75%
  when gross is ₹21,000 or less; professional tax by state; income tax (TDS) under the new regime
  spread evenly over the year. Employer PF (12%) and ESI (3.25%) are shown as cost to company.
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.core.money import ZERO, money

METRO_CITIES = {"chennai", "bengaluru", "hyderabad", "kochi"}
PF_RATE, PF_WAGE_CAP = Decimal("0.12"), Decimal(15_000)
ESI_EMPLOYEE, ESI_EMPLOYER, ESI_LIMIT = Decimal("0.0075"), Decimal("0.0325"), Decimal(21_000)
NIGHT_ALLOWANCE = Decimal(200)
OVERTIME_MIN_MINUTES = 30
STANDARD_DEDUCTION = Decimal(75_000)
# New tax regime (FY 2025-26): (upper limit of the slab, rate)
SLABS = [
    (Decimal(400_000), Decimal("0")),
    (Decimal(800_000), Decimal("0.05")),
    (Decimal(1_200_000), Decimal("0.10")),
    (Decimal(1_600_000), Decimal("0.15")),
    (Decimal(2_000_000), Decimal("0.20")),
    (Decimal(2_400_000), Decimal("0.25")),
    (None, Decimal("0.30")),
]
REBATE_LIMIT = Decimal(1_200_000)  # section 87A: no tax up to ₹12 lakh taxable income
CESS = Decimal("0.04")


def professional_tax(state: str, gross: Decimal) -> Decimal:
    """Monthly professional tax by state (simplified to an even monthly amount)."""
    state = (state or "").lower()
    if state == "karnataka":
        return Decimal(200) if gross >= 25_000 else ZERO
    if state in ("tamil nadu", "kerala"):
        return Decimal(208) if gross >= 21_000 else Decimal(100) if gross >= 12_000 else ZERO
    if state in ("andhra pradesh", "telangana"):
        return Decimal(200) if gross > 20_000 else Decimal(150) if gross > 15_000 else ZERO
    return ZERO


def annual_tax(income: Decimal) -> Decimal:
    taxable = max(ZERO, income - STANDARD_DEDUCTION)
    if taxable <= REBATE_LIMIT:
        return ZERO
    tax, lower = ZERO, ZERO
    for upper, rate in SLABS:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or taxable <= upper:
            break
        lower = upper
    return money(tax * (1 + CESS))


class PayslipStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    APPROVED = "APPROVED", "Approved"
    PAID = "PAID", "Paid"


class SalaryStructure(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="salary"
    )
    monthly_gross = models.DecimalField(max_digits=10, decimal_places=2)
    pf = models.BooleanField(default=True)
    bank_account_last4 = models.CharField(max_length=4, blank=True)
    effective_from = models.DateField()

    class Meta:
        app_label = "workspace"

    def __str__(self) -> str:
        return f"{self.user_id} ₹{self.monthly_gross}"

    def parts(self, city_slug: str) -> dict[str, Decimal]:
        basic = money(self.monthly_gross * Decimal("0.5"))
        hra = money(basic * (Decimal("0.5") if city_slug in METRO_CITIES else Decimal("0.4")))
        return {"basic": basic, "hra": hra, "special": self.monthly_gross - basic - hra}


class Payslip(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payslips"
    )
    month = models.DateField()  # first day of the month
    days = models.PositiveSmallIntegerField()
    paid_days = models.DecimalField(max_digits=4, decimal_places=1)
    lop_days = models.DecimalField(max_digits=4, decimal_places=1, default=ZERO)
    earnings = models.JSONField(default=list)  # [[label, amount]]
    deductions = models.JSONField(default=list)
    employer = models.JSONField(default=list)  # employer contributions (cost to company)
    gross = models.DecimalField(max_digits=10, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=10, decimal_places=2)
    net = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=8, choices=PayslipStatus.choices, default=PayslipStatus.DRAFT
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    bank_reference = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "workspace"
        ordering = ["-month", "user_id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "month"], name="payslip_once_a_month")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.month:%b %Y} ₹{self.net}"


def _q(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _attendance(user, start: date, end: date) -> dict:
    from .attendance import Attendance, AttendanceStatus

    lop, nights, overtime_min = Decimal(0), 0, 0
    for r in Attendance.objects.filter(user=user, day__gte=start, day__lte=end).select_related(
        "shift"
    ):
        if r.status == AttendanceStatus.ABSENT:
            lop += 1
        elif r.status == AttendanceStatus.HALF_DAY:
            lop += Decimal("0.5")
        if r.shift_id and r.shift.slot == "NIGHT" and r.clock_in:
            nights += 1
        if r.clock_in and r.clock_out:
            planned = (r.expected_end - r.expected_start).total_seconds() / 60
            extra = int(r.worked_minutes - planned)
            if extra >= OVERTIME_MIN_MINUTES:
                overtime_min += extra
    return {"lop": lop, "nights": nights, "overtime_min": overtime_min}


def compute(user, month: date) -> dict:
    """The payslip figures for one person and month (no saving)."""
    salary = getattr(user, "salary", None)
    if salary is None:
        raise BusinessRuleViolation(f"{user.get_full_name()} has no salary structure.")
    profile = getattr(user, "staff_profile", None)
    city_slug = profile.city.slug if profile and profile.city_id else ""
    state = profile.state if profile else ""
    month = month.replace(day=1)
    days = monthrange(month.year, month.month)[1]
    end = month.replace(day=days)
    seen = _attendance(user, month, end)
    lop = min(seen["lop"], Decimal(days))
    paid_ratio = (Decimal(days) - lop) / Decimal(days)
    parts = salary.parts(city_slug)
    basic, hra, special = (_q(parts[k] * paid_ratio) for k in ("basic", "hra", "special"))
    hourly_basic = parts["basic"] / Decimal(days) / Decimal(8)
    overtime = _q(hourly_basic * 2 * Decimal(seen["overtime_min"]) / 60)
    night = NIGHT_ALLOWANCE * seen["nights"]
    earnings = [["Basic", basic], ["House rent allowance", hra], ["Special allowance", special]]
    if overtime:
        earnings.append(
            [f"Overtime ({seen['overtime_min'] // 60} h {seen['overtime_min'] % 60} min)", overtime]
        )
    if night:
        earnings.append([f"Night shift allowance ({seen['nights']})", night])
    gross = sum((a for _, a in earnings), ZERO)
    from .expenses import due_for

    reimbursement, _claims = due_for(user)
    pf = _q(min(basic, PF_WAGE_CAP) * PF_RATE) if salary.pf else ZERO
    esi = _q(gross * ESI_EMPLOYEE) if salary.monthly_gross <= ESI_LIMIT else ZERO
    pt = professional_tax(state, gross)
    tds = _q(annual_tax(salary.monthly_gross * 12) / 12)
    deductions = [
        [label, amount]
        for label, amount in (
            ["Provident fund (12% of basic)", pf],
            ["ESI (0.75%)", esi],
            ["Professional tax", pt],
            ["Income tax (TDS, new regime)", tds],
        )
        if amount
    ]
    employer = [
        [label, amount]
        for label, amount in (
            ["Employer PF (12%)", pf],
            ["Employer ESI (3.25%)", _q(gross * ESI_EMPLOYER) if esi else ZERO],
        )
        if amount
    ]
    total = sum((a for _, a in deductions), ZERO)
    if reimbursement:
        # Not salary: no PF, ESI or tax on it, so it's added after the deductions are worked out.
        earnings.append(["Expense reimbursement", reimbursement])
        gross += reimbursement
    return {
        "days": days,
        "paid_days": Decimal(days) - lop,
        "lop_days": lop,
        "earnings": earnings,
        "deductions": deductions,
        "employer": employer,
        "gross": gross,
        "total_deductions": total,
        "net": gross - total,
    }


def _json(lines):
    return [[label, str(amount)] for label, amount in lines]


@transaction.atomic
def run(month: date, *, user=None) -> dict:
    """Create (or refresh) draft payslips for everyone with a salary; approved ones are kept."""
    month = month.replace(day=1)
    if month > timezone.localdate().replace(day=1):
        raise BusinessRuleViolation("Payroll can't be run for a future month.")
    made = refreshed = skipped = 0
    for salary in SalaryStructure.objects.filter(
        effective_from__lte=month + timedelta(days=31)
    ).select_related("user__staff_profile__city"):
        if not salary.user.is_active:
            continue
        existing = Payslip.objects.filter(user=salary.user, month=month).first()
        if existing and existing.status != PayslipStatus.DRAFT:
            skipped += 1
            continue
        figures = compute(salary.user, month)
        fields = {
            **figures,
            "earnings": _json(figures["earnings"]),
            "deductions": _json(figures["deductions"]),
            "employer": _json(figures["employer"]),
        }
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.save()
            slip, refreshed = existing, refreshed + 1
        else:
            slip = Payslip.objects.create(user=salary.user, month=month, **fields)
            made += 1
        from .expenses import due_for

        for claim in due_for(salary.user)[1]:
            claim.payslip = slip
            claim.save(update_fields=["payslip"])
    return {"created": made, "refreshed": refreshed, "kept": skipped}


def approve(month: date, *, user) -> int:
    return Payslip.objects.filter(month=month.replace(day=1), status=PayslipStatus.DRAFT).update(
        status=PayslipStatus.APPROVED, approved_by=user
    )


def mark_paid(month: date, *, user, bank_reference: str, now=None) -> int:
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    if len(bank_reference.strip()) < 4:
        raise BusinessRuleViolation("Enter the bank transfer reference.", field="bank_reference")
    month = month.replace(day=1)
    slips = list(
        Payslip.objects.filter(month=month, status=PayslipStatus.APPROVED).select_related("user")
    )
    if not slips:
        raise InvalidStateTransition("Approve the payslips before marking them paid.")
    now = now or timezone.now()
    Payslip.objects.filter(pk__in=[s.pk for s in slips]).update(
        status=PayslipStatus.PAID, paid_at=now, bank_reference=bank_reference.strip()[:40]
    )
    from .expenses import ClaimStatus, ExpenseClaim

    ExpenseClaim.objects.filter(payslip__in=slips, status=ClaimStatus.APPROVED).update(
        status=ClaimStatus.PAID
    )
    for slip in slips:
        notify(
            slip.user,
            f"Salary for {month:%B %Y} paid",
            f"₹{slip.net:,.2f} has been sent to your bank account. Your payslip is ready.",
            level=Level.SUCCESS,
            link="/ops/payslips",
        )
    return len(slips)


def row(slip: Payslip) -> dict:
    return {
        "id": slip.pk,
        "user_id": slip.user_id,
        "name": slip.user.get_full_name(),
        "role": slip.user.get_role_display(),
        "month": slip.month,
        "days": slip.days,
        "paid_days": slip.paid_days,
        "lop_days": slip.lop_days,
        "earnings": slip.earnings,
        "deductions": slip.deductions,
        "employer": slip.employer,
        "gross": slip.gross,
        "total_deductions": slip.total_deductions,
        "net": slip.net,
        "status": slip.status,
        "status_label": slip.get_status_display(),
        "paid_at": slip.paid_at,
        "bank_reference": slip.bank_reference,
    }


def summary(month: date) -> dict:
    slips = list(Payslip.objects.filter(month=month.replace(day=1)).select_related("user"))
    by_status = defaultdict(int)
    for s in slips:
        by_status[s.status] += 1
    employer = sum((Decimal(a) for s in slips for _, a in s.employer), ZERO)
    gross = sum((s.gross for s in slips), ZERO)
    return {
        "month": month.replace(day=1),
        "people": len(slips),
        "by_status": dict(by_status),
        "gross": gross,
        "net": sum((s.net for s in slips), ZERO),
        "deductions": sum((s.total_deductions for s in slips), ZERO),
        "employer_cost": employer,
        "cost_to_company": gross + employer,
        "lop_days": sum((s.lop_days for s in slips), ZERO),
        "payslips": [row(s) for s in slips],
    }


def render_pdf(slip: Payslip) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.core.conf import company_name

    def rs(amount) -> str:  # the built-in PDF fonts have no rupee glyph
        return f"Rs. {Decimal(amount):,.2f}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        title=f"Payslip {slip.month:%B %Y}",
        author=company_name(),
    )
    styles = getSampleStyleSheet()
    profile = getattr(slip.user, "staff_profile", None)
    story = [
        Paragraph(f"{company_name()} · Payslip for {slip.month:%B %Y}", styles["Title"]),
        Paragraph(
            f"<b>{slip.user.get_full_name()}</b> · {profile.employee_id if profile else ''} · "
            f"{profile.title if profile else slip.user.get_role_display()}",
            styles["Normal"],
        ),
        Paragraph(
            f"Days in month {slip.days} · paid days {slip.paid_days} · loss of pay {slip.lop_days}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]
    rows = [["Earnings", "", "Deductions", ""]]
    for i in range(max(len(slip.earnings), len(slip.deductions))):
        e = slip.earnings[i] if i < len(slip.earnings) else ["", ""]
        d = slip.deductions[i] if i < len(slip.deductions) else ["", ""]
        rows.append([e[0], rs(e[1]) if e[1] != "" else "", d[0], rs(d[1]) if d[1] != "" else ""])
    rows.append(["Gross", rs(slip.gross), "Total deductions", rs(slip.total_deductions)])
    table = Table(rows, colWidths=[55 * mm, 30 * mm, 55 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 6 * mm),
        Paragraph(f"<b>Net pay: {rs(slip.net)}</b>", styles["Heading2"]),
    ]
    if slip.employer:
        story.append(
            Paragraph(
                "Employer contributions (not deducted from you): "
                + ", ".join(f"{label} {rs(amount)}" for label, amount in slip.employer),
                styles["Normal"],
            )
        )
    if slip.paid_at:
        story.append(
            Paragraph(
                f"Paid {timezone.localtime(slip.paid_at):%d %b %Y} · bank reference "
                f"{slip.bank_reference}",
                styles["Normal"],
            )
        )
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph("This is a computer-generated payslip and needs no signature.", styles["Italic"])
    )
    doc.build(story)
    return buffer.getvalue()


# Monthly gross by role (₹), a realistic band for each; the demo picks within it.
SALARY_BANDS = {
    "COMMANDER": (300_000, 350_000),
    "ADMIN": (180_000, 220_000),
    "REGIONAL_MANAGER": (140_000, 170_000),
    "OPS_MANAGER": (75_000, 95_000),
    "ASSOC_RIDES": (60_000, 72_000),
    "ASSOC_SUPPORT": (60_000, 72_000),
    "ASSOC_MAINTENANCE": (60_000, 72_000),
    "ASSOC_INTERCITY": (60_000, 72_000),
    "ASSOC_PARCELS": (60_000, 72_000),
    "SUPPORT_LEAD": (38_000, 46_000),
    "SUPPORT_AGENT": (18_000, 26_000),
    "FLEET_EXECUTIVE": (22_000, 30_000),
}


def seed_demo(*, seed: int = 61, log=print) -> dict:
    """A salary for every employee by role, and last month's payroll run, approved and paid."""
    import random

    from apps.accounts.models import StaffProfile, User

    if SalaryStructure.objects.exists():
        return {"salaries": 0}
    rng = random.Random(seed)
    rows = []
    for profile in StaffProfile.objects.select_related("user"):
        low, high = SALARY_BANDS.get(profile.user.role, (25_000, 35_000))
        rows.append(
            SalaryStructure(
                user=profile.user,
                monthly_gross=Decimal(rng.randrange(low, high + 1, 500)),
                bank_account_last4=f"{rng.randint(0, 9999):04d}",
                effective_from=profile.joined_on,
            )
        )
    SalaryStructure.objects.bulk_create(rows)
    last_month = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
    from apps.notifications import services as notifications

    admin = User.objects.filter(role="ADMIN").first()
    with notifications.muted():
        result = run(last_month, user=admin)
        approve(last_month, user=admin)
        mark_paid(last_month, user=admin, bank_reference=f"HDFC{last_month:%Y%m}SAL01")
    log(f"  payroll: {len(rows)} salaries, {last_month:%B} paid ({result['created']} payslips)")
    return {"salaries": len(rows), "payslips": result["created"]}
