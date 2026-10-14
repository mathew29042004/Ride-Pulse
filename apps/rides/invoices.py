"""Ride invoices, emailed to the rider once the fare is paid (like Rapido's and Uber's).

* Every paid trip gets an invoice number (INV-<year>-000001, gap-free per year).
* The email has a full HTML invoice (fare breakdown with GST, route, times, driver and plate,
  payment), a plain-text version for clients that don't show HTML, and the PDF attached.
* Sent automatically when a trip is paid at drop-off, or later once unpaid dues are cleared.
  Riders can view it in the app and have it sent again. Phone-only accounts (placeholder
  ``.invalid`` address) get it once they add an email.
"""

from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.conf import (
    company_address,
    company_gstin,
    company_name,
    currency_symbol,
    support_email,
)
from apps.core.sequences import next_reference
from apps.payments.models import PaymentMethod

from .models import PricingMode, Trip, TripPaymentStatus, TripStatus

# Reserved domains (RFC 2606): phone-only placeholders and the simulator's synthetic riders.
UNDELIVERABLE = (".invalid", "@example.com", ".example.com")


def can_email(trip: Trip) -> bool:
    email = trip.rider.user.email.lower()
    return bool(email) and not email.endswith(UNDELIVERABLE)


def ensure_number(trip: Trip) -> str:
    """Give a paid trip its invoice number (once)."""
    if not trip.invoice_number:
        at = trip.completed_at or timezone.now()
        number = next_reference("INV", year=at.year, width=6)
        updated = Trip.objects.filter(pk=trip.pk, invoice_number="").update(invoice_number=number)
        trip.invoice_number = (
            number
            if updated
            else Trip.objects.values_list("invoice_number", flat=True).get(pk=trip.pk)
        )
    return trip.invoice_number


def context(trip: Trip) -> dict:
    fare = trip.final_fare
    local = timezone.localtime
    started, completed = trip.started_at, trip.completed_at
    vehicle = trip.vehicle
    tip = trip.tip_amount or 0
    return {
        "trip": trip,
        "rider_first_name": trip.rider.user.first_name or "there",
        "currency": currency_symbol(),
        "company": company_name(),
        "company_gstin": company_gstin(),
        "company_address": company_address(),
        "support_email": support_email(),
        "invoice_number": trip.invoice_number,
        "issued_on": local(completed or timezone.now()),
        "ride_type": trip.ride_type.name,
        "pickup_time": local(started) if started else None,
        "drop_time": local(completed) if completed else None,
        "distance_km": trip.actual_distance_km or trip.estimated_distance_km,
        "duration_min": trip.actual_duration_min or trip.estimated_duration_min,
        "lines": fare.lines,
        "total": fare.total,
        "tip": tip,
        "amount_paid": fare.total + tip,
        "payment_method": PaymentMethod(trip.payment_method).label,
        "payment_status": trip.get_payment_status_display(),
        "driver_name": trip.driver.user.get_full_name() if trip.driver else "",
        "vehicle_model": f"{vehicle.color} {vehicle.make} {vehicle.model}".strip()
        if vehicle
        else "",
        "vehicle_plate": vehicle.registration_display if vehicle else "",
        "promo_code": trip.promo.code if trip.promo_id else "",
        # Upfront pricing: the fare was fixed for the planned route before the ride, so the
        # lines may show different km/min than the ride itself (that's the promise, not a bug).
        "upfront": trip.pricing_mode == PricingMode.UPFRONT,
        "planned_km": trip.estimated_distance_km,
        "planned_min": trip.estimated_duration_min,
    }


def render_html(trip: Trip) -> str:
    return render_to_string("rides/invoice_email.html", context(trip))


def send(trip: Trip, *, force: bool = False) -> bool:
    """Email the invoice. Returns False if there's nothing to send (unpaid, no address, or
    already sent and not forced)."""
    from .receipts import render_receipt

    trip = (
        Trip.objects.select_related("rider__user", "driver__user", "vehicle", "ride_type", "promo")
        .filter(pk=trip.pk)
        .first()
    )
    if (
        trip is None
        or trip.status != TripStatus.COMPLETED
        or trip.payment_status != TripPaymentStatus.PAID
    ):
        return False
    if not can_email(trip) or (trip.invoice_emailed_at and not force):
        return False
    ensure_number(trip)
    data = context(trip)
    when = data["issued_on"]
    message = EmailMultiAlternatives(
        subject=f"Your {company_name()} invoice · {currency_symbol()}{data['amount_paid']:,.2f} · "
        f"{when:%d %b, %I:%M %p}",
        body=render_to_string("rides/invoice_email.txt", data),
        to=[trip.rider.user.email],
        reply_to=[support_email()],
    )
    message.attach_alternative(render_to_string("rides/invoice_email.html", data), "text/html")
    message.attach(f"Ride-Pulse-{trip.invoice_number}.pdf", render_receipt(trip), "application/pdf")
    message.send()
    Trip.objects.filter(pk=trip.pk).update(invoice_emailed_at=timezone.now())
    return True


def send_after_commit(trip: Trip) -> None:
    """Number the invoice now; email it in the background once the payment is committed."""
    from .tasks import email_invoice

    ensure_number(trip)
    if can_email(trip):
        transaction.on_commit(lambda: email_invoice.delay(trip.pk))
