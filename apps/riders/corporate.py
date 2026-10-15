"""Corporate portal (like Uber for Business): a company's travel dashboard for its owner and
travel admins.

* Policy: allowed ride types, hours, a fare cap per trip, and cost centres (each employee can
  have a default). Enforced at booking (``profiles.check_policy``).
* Spend: this month and the last six, by employee, cost centre and ride type, with the purpose
  of each trip.
* A consolidated monthly GST invoice (PDF) for the accounts team.
* Webhooks: the company's own endpoint receives its employees' trip events (from the outbox).
"""

from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation

from .models import MemberStatus, PaymentProfile, ProfileKind, RiderProfile

ZERO = Decimal("0")


def can_manage(profile: PaymentProfile, rider: RiderProfile) -> bool:
    if profile.kind != ProfileKind.BUSINESS:
        return False
    return (
        profile.owner_id == rider.pk
        or profile.members.filter(rider=rider, status=MemberStatus.ACTIVE, is_admin=True).exists()
    )


def require_manager(profile: PaymentProfile, rider: RiderProfile) -> None:
    if not can_manage(profile, rider):
        raise ActionNotPermitted("Only the company's owner and travel admins can do this.")


def _month_start(at: datetime) -> datetime:
    local = timezone.localtime(at)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _completed(profile: PaymentProfile):
    from apps.rides.models import TripStatus

    return profile.trips.filter(status=TripStatus.COMPLETED)


def dashboard(profile: PaymentProfile, *, now: datetime | None = None) -> dict:
    from apps.payments.services import wallet_balance

    now = now or timezone.now()
    month = _month_start(now)
    trips = _completed(profile)
    this_month = trips.filter(completed_at__gte=month)
    totals = this_month.aggregate(spend=Sum("fare_total", default=ZERO), rides=Count("pk"))
    by_month = list(
        trips.filter(completed_at__gte=month - timedelta(days=185))
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(spend=Sum("fare_total"), rides=Count("pk"))
        .order_by("month")
    )
    by_employee = list(
        this_month.values("rider_id", "rider__user__first_name", "rider__user__last_name")
        .annotate(spend=Sum("fare_total"), rides=Count("pk"))
        .order_by("-spend")[:20]
    )
    by_cost_center = list(
        this_month.values("cost_center")
        .annotate(spend=Sum("fare_total"), rides=Count("pk"))
        .order_by("-spend")
    )
    by_ride_type = list(
        this_month.values("ride_type__name")
        .annotate(spend=Sum("fare_total"), rides=Count("pk"))
        .order_by("-spend")
    )
    recent = [
        {
            "trip_number": t.trip_number,
            "employee": t.rider.user.get_full_name(),
            "when": t.completed_at.isoformat(),
            "route": f"{t.pickup_address} → {t.dropoff_address}",
            "ride_type": t.ride_type.name,
            "fare": str(t.fare_total),
            "purpose": t.trip_purpose,
            "cost_center": t.cost_center,
        }
        for t in trips.select_related("rider__user", "ride_type").order_by("-completed_at")[:25]
    ]
    members = profile.members.select_related("rider__user").exclude(status=MemberStatus.REMOVED)
    return {
        "id": profile.pk,
        "company": profile.name,
        "gstin": profile.gstin,
        "balance": str(wallet_balance(profile.owner.user)),
        "credit_limit": str(profile.credit_limit),
        "policy": {
            "allowed_ride_types": profile.allowed_ride_types,
            "allowed_from_hour": profile.allowed_from_hour,
            "allowed_to_hour": profile.allowed_to_hour,
            "max_fare_per_trip": str(profile.max_fare_per_trip)
            if profile.max_fare_per_trip
            else None,
            "cost_centers": profile.cost_centers,
        },
        "this_month": {"spend": str(totals["spend"]), "rides": totals["rides"]},
        "by_month": [
            {
                "month": r["month"].date().isoformat()[:7],
                "spend": str(r["spend"]),
                "rides": r["rides"],
            }
            for r in by_month
        ],
        "by_employee": [
            {
                "rider_id": r["rider_id"],
                "name": f"{r['rider__user__first_name']} {r['rider__user__last_name']}".strip(),
                "spend": str(r["spend"]),
                "rides": r["rides"],
            }
            for r in by_employee
        ],
        "by_cost_center": [
            {"cost_center": r["cost_center"] or "—", "spend": str(r["spend"]), "rides": r["rides"]}
            for r in by_cost_center
        ],
        "by_ride_type": [
            {"ride_type": r["ride_type__name"], "spend": str(r["spend"]), "rides": r["rides"]}
            for r in by_ride_type
        ],
        "employees": [
            {
                "member_id": m.pk,
                "name": m.rider.user.get_full_name(),
                "status": m.status,
                "is_admin": m.is_admin,
                "monthly_limit": str(m.monthly_limit) if m.monthly_limit else None,
                "default_cost_center": m.default_cost_center,
            }
            for m in members
        ],
        "recent": recent,
        "webhooks": [
            {"id": w.pk, "name": w.name, "url": w.url, "topics": w.topics, "is_active": w.is_active}
            for w in profile.webhooks.all()
        ],
    }


@transaction.atomic
def update_policy(profile: PaymentProfile, *, rider: RiderProfile, **policy) -> PaymentProfile:
    require_manager(profile, rider)
    from apps.pricing.models import RideType

    types = policy.get("allowed_ride_types")
    if types is not None:
        known = set(RideType.objects.values_list("code", flat=True))
        if set(types) - known:
            raise BusinessRuleViolation("Unknown ride type.", field="allowed_ride_types")
        profile.allowed_ride_types = sorted(set(types))
    for hour in ("allowed_from_hour", "allowed_to_hour"):
        if hour in policy:
            value = policy[hour]
            if value is not None and not 0 <= value <= 23:
                raise BusinessRuleViolation("Hours are 0-23.", field=hour)
            setattr(profile, hour, value)
    if "max_fare_per_trip" in policy:
        profile.max_fare_per_trip = policy["max_fare_per_trip"]
    if "cost_centers" in policy:
        centres = [" ".join(c.split())[:40] for c in policy["cost_centers"] if c.strip()]
        profile.cost_centers = sorted(set(centres))
    profile.save()
    return profile


def update_employee(profile: PaymentProfile, *, rider: RiderProfile, member_id: int, **changes):
    require_manager(profile, rider)
    member = profile.members.get(pk=member_id)
    if "is_admin" in changes:
        if profile.owner_id != rider.pk:
            raise ActionNotPermitted("Only the owner can make travel admins.")
        member.is_admin = bool(changes["is_admin"])
    if "default_cost_center" in changes:
        centre = changes["default_cost_center"] or ""
        if centre and centre not in profile.cost_centers:
            raise BusinessRuleViolation("Unknown cost centre.", field="default_cost_center")
        member.default_cost_center = centre
    member.save()
    return member


def add_webhook(profile: PaymentProfile, *, rider: RiderProfile, name: str, url: str):
    from apps.reliability import outbox
    from apps.reliability.models import WebhookEndpoint

    require_manager(profile, rider)
    if not url.startswith("https://"):
        raise BusinessRuleViolation("Webhook URLs must use HTTPS.", field="url")
    return WebhookEndpoint.objects.create(
        name=name[:80],
        url=url,
        secret=outbox.new_secret(),
        topics=["trip.completed", "trip.cancelled", "payment.refunded"],
        corporate=profile,
        created_by=rider.user,
    )


def invoice_pdf(profile: PaymentProfile, *, month: str | None = None) -> tuple[bytes, str]:
    """One consolidated GST invoice for the month's rides (fares include GST at 5%)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.core.conf import company_gstin, company_name, gst_rate

    now = timezone.now()
    if month:
        try:
            start = timezone.make_aware(datetime.strptime(month, "%Y-%m"))
        except ValueError as exc:
            raise BusinessRuleViolation("Use the YYYY-MM format.", field="month") from exc
    else:
        start = _month_start(now)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    trips = (
        _completed(profile)
        .filter(completed_at__gte=start, completed_at__lt=end)
        .select_related("rider__user", "ride_type")
        .order_by("completed_at")
    )
    total = sum((t.fare_total or ZERO for t in trips), ZERO)
    rate = gst_rate()  # a fraction: 0.05 = 5%
    taxable = (total / (1 + rate)).quantize(Decimal("0.01"))
    gst = total - taxable
    number = f"CORP-{start:%Y%m}-{profile.pk:05d}"

    def rs(amount) -> str:
        return f"Rs. {Decimal(amount):,.2f}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, title=number
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Ride Pulse · Tax invoice", styles["Title"]),
        Paragraph(
            f"{company_name()} · GSTIN {company_gstin()} · Invoice {number}", styles["Normal"]
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            f"<b>Billed to:</b> {profile.name}"
            + (f" · GSTIN {profile.gstin}" if profile.gstin else "")
            + f"<br/><b>Period:</b> {start:%B %Y} · {trips.count()} rides",
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]
    rows = [["Date", "Trip", "Employee", "Purpose", "Cost centre", "Fare"]]
    for t in trips[:400]:
        rows.append(
            [
                f"{timezone.localtime(t.completed_at):%d %b}",
                t.trip_number,
                t.rider.user.get_full_name()[:22],
                (t.trip_purpose or "")[:28],
                t.cost_center or "—",
                rs(t.fare_total or 0),
            ]
        )
    rows += [
        ["", "", "", "", "Taxable value", rs(taxable)],
        ["", "", "", "", f"GST ({rate * 100:g}%)", rs(gst)],
        ["", "", "", "", "Total", rs(total)],
    ]
    table = Table(
        rows, repeatRows=1, colWidths=[16 * mm, 32 * mm, 36 * mm, 44 * mm, 24 * mm, 26 * mm]
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buffer.getvalue(), number
