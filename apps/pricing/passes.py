"""Ride Pass: a monthly subscription (₹99 / 30 days by default) giving 10% off every ride, up to
₹30, and no booking fee. The saving is funded by the platform like a promo, so drivers earn the
same. Paid from the wallet or by UPI/card; the money is platform subscription revenue."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.conf import ride_pass_terms
from apps.core.exceptions import BusinessRuleViolation
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import RidePass


def active_pass(rider, at: datetime | None = None) -> RidePass | None:
    at = at or timezone.now()
    return rider.passes.filter(starts_at__lte=at, ends_at__gt=at).first()


def pass_terms_for(rider, at: datetime | None = None) -> tuple[Decimal | None, Decimal]:
    """(percent, max discount) for the fare engine; (None, 0) without a pass."""
    if rider is None or active_pass(rider, at) is None:
        return None, Decimal(0)
    terms = ride_pass_terms()
    return terms["percent"], terms["max_discount"]


@transaction.atomic
def buy_pass(
    rider, *, method: str, payer_reference: str = "", now: datetime | None = None
) -> RidePass:
    from apps.payments import accounts
    from apps.payments.models import PaymentMethod, PaymentPurpose, PaymentStatus, TransactionKind
    from apps.payments.services import ensure_wallet, gateway_charge, post, wallet_balance

    now = now or timezone.now()
    terms = ride_pass_terms()
    price = terms["price"]
    reference = next_reference("PASS", year=now.year, width=6)
    if method == PaymentMethod.WALLET:
        if wallet_balance(rider.user) < price:
            raise BusinessRuleViolation(
                "Not enough wallet balance for the Ride Pass.", field="method"
            )
        source = ensure_wallet(rider.user)
    elif method in (PaymentMethod.UPI, PaymentMethod.CARD):
        payment, _ = gateway_charge(
            user=rider.user,
            amount=price,
            method=method,
            purpose=PaymentPurpose.PASS,
            payer_reference=payer_reference,
        )
        if payment.status != PaymentStatus.SUCCEEDED:
            raise BusinessRuleViolation(f"Payment failed: {payment.failure_reason}")
        source = accounts.GATEWAY
    else:
        raise BusinessRuleViolation("Pay with UPI, card or your wallet.", field="method")
    post(
        TransactionKind.RIDE_PASS,
        [(source, -price), (accounts.PLATFORM_SUBSCRIPTIONS, price)],
        description=f"Ride Pass {reference}",
        at=now,
    )
    current = rider.passes.filter(ends_at__gt=now).order_by("-ends_at").first()
    starts = current.ends_at if current else now  # renewing early never wastes days
    ride_pass = RidePass.objects.create(
        rider=rider,
        price=price,
        starts_at=starts,
        ends_at=starts + timedelta(days=terms["days"]),
        payment_method=method,
        reference=reference,
    )
    notify(
        rider.user,
        "Ride Pass active",
        f"{terms['percent']:.0f}% off every ride (up to ₹{terms['max_discount']:.0f}) and no "
        f"booking fee until {timezone.localtime(ride_pass.ends_at):%d %b}.",
        level=Level.SUCCESS,
        link="/ride/wallet/",
    )
    return ride_pass


def savings(rider) -> Decimal:
    """What the pass has saved this rider so far (discount lines on completed trips)."""
    from apps.rides.models import Trip, TripStatus

    total = Decimal(0)
    for breakdown in Trip.objects.filter(
        rider=rider, status=TripStatus.COMPLETED, ride_pass_applied=True
    ).values_list("fare_breakdown", flat=True):
        for line in (breakdown or {}).get("lines", []):
            if line["code"] in ("RIDE_PASS",):
                total -= Decimal(line["amount"])
    return total
