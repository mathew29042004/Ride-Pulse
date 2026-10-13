"""PDF trip receipts (ReportLab). The built-in PDF fonts have no rupee glyph, so amounts use
"Rs."."""

from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.conf import company_name

from .models import Trip

BRAND = colors.HexColor("#111827")
ACCENT = colors.HexColor("#10b981")
MUTED = colors.HexColor("#6b7280")


def _rs(amount) -> str:
    return f"Rs. {amount:,.2f}"


def render_receipt(trip: Trip) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Receipt {trip.trip_number}",
        author=company_name(),
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "title", parent=styles["Title"], textColor=BRAND, fontSize=20, spaceAfter=2
    )
    small = ParagraphStyle(
        "small", parent=styles["Normal"], textColor=MUTED, fontSize=8, leading=10
    )
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12)
    fare = trip.final_fare
    completed = timezone.localtime(trip.completed_at or trip.requested_at)

    story = [
        Paragraph("Ride Pulse", title),
        Paragraph(f"{company_name()} · Trip receipt", small),
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>{_rs(trip.fare_total or trip.estimated_fare)}</b>",
            ParagraphStyle("total", fontSize=22, leading=26, textColor=BRAND),
        ),
        Paragraph(
            f"{trip.ride_type.name} · {completed:%d %b %Y, %I:%M %p} · {trip.trip_number}", small
        ),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>From</b> {trip.pickup_address or 'Pickup'}", body),
        Paragraph(f"<b>To</b> {trip.dropoff_address or 'Drop'}", body),
        Spacer(1, 2 * mm),
    ]
    details = [
        ["Rider", trip.rider.name],
        ["Driver", trip.driver.name if trip.driver else "—"],
        ["Vehicle", str(trip.vehicle) if trip.vehicle else "—"],
        ["Distance", f"{trip.actual_distance_km or trip.estimated_distance_km} km"],
        ["Duration", f"{trip.actual_duration_min or trip.estimated_duration_min} min"],
        ["Payment", trip.get_payment_status_display() + f" ({trip.payment_method.title()})"],
    ]
    story.append(_table(details, highlight_last=False))
    story.append(Spacer(1, 4 * mm))
    lines = [[line.label, _rs(line.amount)] for line in fare.lines]
    lines.append(["Total", _rs(fare.total)])
    if trip.tip_amount:
        lines.append(["Tip (100% to driver)", _rs(trip.tip_amount)])
    story.append(_table(lines, highlight_last=not trip.tip_amount))
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Fares include 5% GST on passenger transport services. Promotional discounts are "
            "funded by Ride Pulse and don't reduce your driver's earnings. This is a demo receipt.",
            small,
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _table(rows: list[list[str]], *, highlight_last: bool) -> Table:
    table = Table(rows, colWidths=[70 * mm, 50 * mm])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    if highlight_last:
        style += [
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, -1), (-1, -1), BRAND),
            ("LINEABOVE", (0, -1), (-1, -1), 1, ACCENT),
        ]
    table.setStyle(TableStyle(style))
    return table
