"""Parcel delivery (like Rapido Parcel): a bike driver carries a package from the sender to a
recipient.

The sender books a PARCEL trip with the recipient's name and phone, what's inside and the
weight (up to 10 kg). The driver starts with the sender's PIN, exactly like a ride. When the
parcel is picked up the recipient gets an SMS with a live tracking link and a 4-digit delivery
code; the driver can only complete the delivery by entering that code at the door, so a parcel
is never marked delivered without the recipient. Passenger-safety features (Night Safe, Ride
Check, trusted contacts) don't apply: there's no one riding.
"""

import logging
import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts import sms
from apps.core import conf
from apps.core.exceptions import BusinessRuleViolation
from apps.core.validators import normalize_indian_mobile

from .models import ParcelCategory, ParcelDelivery, Trip

logger = logging.getLogger(__name__)

MAX_WEIGHT_KG = Decimal(10)
MAX_CODE_ATTEMPTS = 5
PROHIBITED = "No cash, jewellery, medicines needing a prescription, alcohol, or anything illegal."


def clean(data: dict) -> dict:
    """Validate the parcel details from the booking form."""
    name = " ".join(str(data.get("recipient_name", "")).split())[:80]
    if len(name) < 2:
        raise BusinessRuleViolation("Enter the recipient's name.", field="recipient_name")
    try:
        phone = normalize_indian_mobile(str(data.get("recipient_phone", "")))
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="recipient_phone") from exc
    category = data.get("category") or ParcelCategory.OTHER
    if category not in ParcelCategory.values:
        raise BusinessRuleViolation("Choose what you're sending.", field="category")
    weight = Decimal(str(data.get("weight_kg") or 1))
    if not Decimal("0.1") <= weight <= MAX_WEIGHT_KG:
        raise BusinessRuleViolation(
            f"Parcels can weigh up to {MAX_WEIGHT_KG:.0f} kg.", field="weight_kg"
        )
    return {
        "recipient_name": name,
        "recipient_phone": phone,
        "category": category,
        "weight_kg": weight,
        "instructions": " ".join(str(data.get("instructions", "")).split())[:200],
    }


def create(trip: Trip, details: dict) -> ParcelDelivery:
    return ParcelDelivery.objects.create(
        trip=trip, delivery_code=f"{secrets.randbelow(10_000):04d}", **details
    )


def notify_recipient(trip_id: int) -> bool:
    """When the parcel is picked up: tracking link + delivery code to the recipient (once)."""
    trip = Trip.objects.select_related("rider__user", "parcel").get(pk=trip_id)
    parcel = trip.parcel
    if parcel.recipient_notified_at:
        return False
    if not trip.share_token:
        trip.share_token = secrets.token_urlsafe(18)
        trip.save(update_fields=["share_token", "updated_at"])
    try:
        sms.send_text(
            parcel.recipient_phone,
            f"{trip.rider.name} sent you a parcel on Ride Pulse. It's on the way: "
            f"{conf.app_url()}/track/{trip.share_token} . Give the driver code "
            f"{parcel.delivery_code} when it arrives.",
        )
    except sms.SMSError as exc:
        logger.warning("Couldn't text parcel recipient for trip %s: %s", trip.pk, exc)
    ParcelDelivery.objects.filter(pk=parcel.pk).update(recipient_notified_at=timezone.now())
    return True


def verify_code(trip: Trip, code: str | None) -> ParcelDelivery:
    """The recipient's code proves the hand-over. Wrong attempts are saved before the error is
    raised, so they can't be retried for ever."""
    with transaction.atomic():
        parcel = ParcelDelivery.objects.select_for_update().get(trip=trip)
        if parcel.delivered_at:
            return parcel
        if parcel.code_attempts >= MAX_CODE_ATTEMPTS:
            raise BusinessRuleViolation(
                "Too many wrong codes. Call support to complete this delivery.",
                field="delivery_code",
            )
        if code and secrets.compare_digest(str(code).strip(), parcel.delivery_code):
            parcel.delivered_at = timezone.now()
            parcel.save(update_fields=["delivered_at"])
            return parcel
        parcel.code_attempts += 1
        parcel.save(update_fields=["code_attempts"])
        left = MAX_CODE_ATTEMPTS - parcel.code_attempts
    raise BusinessRuleViolation(
        f"Wrong delivery code. Ask the recipient for the 4-digit code from their SMS "
        f"({left} {'try' if left == 1 else 'tries'} left).",
        field="delivery_code",
    )


def assert_delivered(trip: Trip) -> None:
    """Called by ``complete_trip``: a parcel trip ends only after the code was verified."""
    if not ParcelDelivery.objects.filter(trip=trip, delivered_at__isnull=False).exists():
        raise BusinessRuleViolation(
            "Enter the recipient's delivery code to complete this delivery.",
            field="delivery_code",
        )
