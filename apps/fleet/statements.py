"""Weekly driver statements and TDS.

Every Monday, before payouts, each driver who worked last week gets a statement: trips, what
riders paid, commission, tips, bonuses, cancellation fees, any fleet owner's share and the net.

Ride Pulse is an "e-commerce operator" under section 194-O of the Income Tax Act, so it withholds
TDS on drivers' gross fares: 0.1% when the driver's PAN is on file (from 1 October 2024), 5%
without one (section 206AA). The tax moves from the driver's wallet to ``tax:tds_payable`` in the
ledger, ready to deposit with the government; the quarterly report backs the TDS return.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.conf import _decimal, company_gstin, company_name
from apps.core.dates import week_start as monday
from apps.core.sequences import next_reference
from apps.drivers.models import DocumentStatus, DocumentType, DriverDocument, DriverProfile
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.payments import accounts
from apps.payments.models import LedgerEntry, TransactionKind
from apps.payments.services import driver_earnings, ensure_wallet, post
from apps.rides.models import Trip, TripStatus

from .models import DriverStatement

ZERO = Decimal("0")
CENT = Decimal("0.01")


def pan_on_file(driver: DriverProfile) -> bool:
    return DriverDocument.objects.filter(
        driver=driver, doc_type=DocumentType.PAN, status=DocumentStatus.APPROVED
    ).exists()


def tds_rate(driver: DriverProfile) -> Decimal:
    return _decimal("TDS_RATE_WITH_PAN" if pan_on_file(driver) else "TDS_RATE_WITHOUT_PAN")


def _bounds(start: date) -> tuple[datetime, datetime]:
    begin = timezone.make_aware(datetime.combine(start, time.min))
    return begin, begin + timedelta(days=7)


def _ledger_total(driver: DriverProfile, kinds, begin: datetime, end: datetime) -> Decimal:
    return LedgerEntry.objects.filter(
        wallet__user=driver.user,
        transaction__kind__in=kinds,
        transaction__created_at__gte=begin,
        transaction__created_at__lt=end,
    ).aggregate(total=Sum("amount", default=ZERO))["total"]


@transaction.atomic
def create_statement(
    driver: DriverProfile, week: date, *, now: datetime | None = None, notify_driver: bool = True
) -> DriverStatement | None:
    """The statement for the week starting ``week`` (a Monday); withholds TDS once."""
    now = now or timezone.now()
    existing = DriverStatement.objects.filter(driver=driver, week_start=week).first()
    if existing:
        return existing
    begin, end = _bounds(week)
    money = driver_earnings(driver, start=begin, end=end)
    if not money["trips"]:
        return None
    pan = pan_on_file(driver)
    rate = tds_rate(driver)
    gross = money["fares"]
    tds = (gross * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    bonuses = _ledger_total(
        driver, [TransactionKind.DRIVER_BONUS, TransactionKind.INCENTIVE], begin, end
    )
    fleet_share = -_ledger_total(driver, [TransactionKind.FLEET_SHARE], begin, end)
    statement = DriverStatement.objects.create(
        number=next_reference("DST", year=week.year),
        driver=driver,
        week_start=week,
        week_end=week + timedelta(days=6),
        trips=money["trips"],
        gross_fares=gross,
        commission=money["commission"],
        trip_earnings=money["trip_earnings"],
        tips=money["tips"],
        bonuses=bonuses,
        cancellation_fees=money["cancellation_fees"],
        fleet_share=fleet_share,
        cash_collected=money["cash_collected"],
        distance_km=money["distance_km"],
        pan_on_file=pan,
        tds_rate=rate,
        tds_amount=tds,
        net_earnings=money["earnings"] + bonuses - fleet_share - tds,
        created_at=now,
    )
    if tds:
        post(
            TransactionKind.TDS,
            [(ensure_wallet(driver.user), -tds), (accounts.TDS_PAYABLE, tds)],
            description=f"TDS {rate * 100:g}% on ₹{gross} fares, {statement.number}",
            at=now,
        )
    if notify_driver:
        notify(
            driver.user,
            f"Your statement for {week:%d %b} – {statement.week_end:%d %b}",
            f"{statement.trips} trips · net ₹{statement.net_earnings}"
            + ("" if pan else " · add your PAN to cut TDS from 5% to 0.1%"),
            level=Level.INFO if pan else Level.WARNING,
            link="/drive/earnings",
        )
    return statement


def generate_week(week: date | None = None, *, now: datetime | None = None) -> int:
    """Statements for everyone who drove in ``week`` (default: last week)."""
    now = now or timezone.now()
    week = week or monday(timezone.localdate(now)) - timedelta(days=7)
    begin, end = _bounds(week)
    driver_ids = (
        Trip.objects.filter(
            status=TripStatus.COMPLETED, completed_at__gte=begin, completed_at__lt=end
        )
        .values_list("driver_id", flat=True)
        .distinct()
    )
    made = 0
    for driver in DriverProfile.objects.filter(pk__in=driver_ids).select_related("user"):
        if not DriverStatement.objects.filter(driver=driver, week_start=week).exists():
            made += bool(create_statement(driver, week, now=now))
    return made


# --- Quarterly TDS report ---------------------------------------------------------------------


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """Indian financial-year quarters: Q1 = Apr-Jun ... Q4 = Jan-Mar (of ``year`` + 1)."""
    start_month = {1: 4, 2: 7, 3: 10, 4: 1}[quarter]
    start_year = year + 1 if quarter == 4 else year
    start = date(start_year, start_month, 1)
    end_month = start_month + 3
    end = date(start_year + (end_month > 12), (end_month - 1) % 12 + 1, 1)
    return start, end


def current_quarter(today: date) -> tuple[int, int]:
    fy = today.year if today.month >= 4 else today.year - 1
    return fy, {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3}.get(today.month, 4)


def tds_report(year: int, quarter: int) -> dict:
    start, end = quarter_bounds(year, quarter)
    rows = DriverStatement.objects.filter(week_start__gte=start, week_start__lt=end)
    totals = rows.aggregate(
        gross=Sum("gross_fares", default=ZERO), tds=Sum("tds_amount", default=ZERO)
    )
    per_driver = (
        rows.values(
            "driver_id", "driver__user__first_name", "driver__user__last_name", "pan_on_file"
        )
        .annotate(gross=Sum("gross_fares"), tds=Sum("tds_amount"))
        .order_by("-tds")
    )
    return {
        "financial_year": f"{year}-{str(year + 1)[2:]}",
        "quarter": quarter,
        "from": start.isoformat(),
        "to": (end - timedelta(days=1)).isoformat(),
        "statements": rows.count(),
        "drivers": per_driver.count(),
        "gross_fares": str(totals["gross"]),
        "tds_withheld": str(totals["tds"]),
        "without_pan": rows.filter(pan_on_file=False).values("driver_id").distinct().count(),
        "rows": [
            {
                "driver_id": r["driver_id"],
                "name": f"{r['driver__user__first_name']} {r['driver__user__last_name']}".strip(),
                "pan_on_file": r["pan_on_file"],
                "gross_fares": str(r["gross"]),
                "tds": str(r["tds"]),
            }
            for r in per_driver
        ],
    }


# --- PDF -------------------------------------------------------------------------------------


def render_pdf(statement: DriverStatement) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def rs(amount) -> str:  # the built-in PDF fonts have no rupee glyph
        return f"Rs. {Decimal(amount):,.2f}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        title=f"Statement {statement.number}",
        author=company_name(),
    )
    styles = getSampleStyleSheet()
    driver = statement.driver
    story = [
        Paragraph("Ride Pulse · Weekly driver statement", styles["Title"]),
        Paragraph(
            f"{company_name()} · GSTIN {company_gstin()} · {statement.number}", styles["Normal"]
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>{driver.name}</b> · {statement.week_start:%d %b %Y} – "
            f"{statement.week_end:%d %b %Y} · {statement.trips} trips · "
            f"{statement.distance_km} km",
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]
    lines = [
        ["Riders paid (gross fares)", rs(statement.gross_fares)],
        ["Ride Pulse commission", f"- {rs(statement.commission)}"],
        ["Your trip earnings", rs(statement.trip_earnings)],
        ["Tips (100% yours)", rs(statement.tips)],
        ["Bonuses and incentives", rs(statement.bonuses)],
        ["Cancellation fees", rs(statement.cancellation_fees)],
    ]
    if statement.fleet_share:
        lines.append(["Fleet owner's share", f"- {rs(statement.fleet_share)}"])
    lines += [
        [
            f"TDS u/s 194-O at {statement.tds_rate * 100:g}%"
            + ("" if statement.pan_on_file else " (no PAN on file)"),
            f"- {rs(statement.tds_amount)}",
        ],
        ["Net earnings", rs(statement.net_earnings)],
        ["Cash collected from riders (already with you)", rs(statement.cash_collected)],
    ]
    table = Table(lines, colWidths=[120 * mm, 50 * mm])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
                ("FONTNAME", (0, -2), (-1, -2), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 8 * mm),
        Paragraph(
            "TDS withheld is deposited with the Income Tax Department and appears in your "
            "Form 26AS. Claim it when you file your return."
            + ("" if statement.pan_on_file else " Upload your PAN card to pay 0.1% instead of 5%."),
            styles["Italic"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
