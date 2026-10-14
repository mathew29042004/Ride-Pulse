"""Split fare: after a paid ride, the rider asks up to three friends (Ride Pulse riders, by
phone number) for an equal share. Each friend pays their share by UPI, card or wallet, and it
lands in the rider's wallet, as a balanced ledger transaction."""

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    InvalidStateTransition,
)
from apps.core.validators import normalize_indian_mobile
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import FareSplit, FareSplitStatus, Trip, TripPaymentStatus, TripStatus

MAX_FRIENDS = 3
SPLIT_WINDOW = timedelta(days=7)


def _rider_by_phone(phone: str):
    from apps.riders.models import RiderProfile

    try:
        phone = normalize_indian_mobile(phone)
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="phones") from exc
    rider = RiderProfile.objects.select_related("user").filter(user__phone=phone).first()
    if rider is None:
        raise BusinessRuleViolation(
            f"No Ride Pulse rider uses +91 {phone}. Ask them to sign up first.", field="phones"
        )
    return rider


@transaction.atomic
def request_split(trip: Trip, *, user, phones: list[str]) -> list[FareSplit]:
    trip = Trip.objects.select_for_update().select_related("rider__user").get(pk=trip.pk)
    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider who paid can split the fare.")
    if trip.status != TripStatus.COMPLETED or trip.payment_status != TripPaymentStatus.PAID:
        raise InvalidStateTransition("You can split the fare once the ride is paid.")
    if timezone.now() - trip.completed_at > SPLIT_WINDOW:
        raise BusinessRuleViolation("Fares can be split for 7 days after the ride.")
    if trip.splits.exclude(status=FareSplitStatus.CANCELLED).exists():
        raise ConflictError("This fare is already split.")
    friends = []
    for phone in phones:
        friend = _rider_by_phone(phone)
        if friend.pk == trip.rider_id:
            raise BusinessRuleViolation("That's your own number.", field="phones")
        if friend not in friends:
            friends.append(friend)
    if not 1 <= len(friends) <= MAX_FRIENDS:
        raise BusinessRuleViolation(f"Split with 1 to {MAX_FRIENDS} friends.", field="phones")
    share = (trip.fare_total / (len(friends) + 1)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    splits = []
    for friend in friends:
        split, _ = FareSplit.objects.update_or_create(
            trip=trip,
            friend=friend,
            defaults={"amount": share, "status": FareSplitStatus.REQUESTED, "responded_at": None},
        )
        splits.append(split)
        notify(
            friend.user,
            f"{trip.rider.user.first_name or 'A friend'} split a ride with you: ₹{share}",
            f"{trip.ride_type.name} to {trip.dropoff_address or 'their destination'}. "
            "Pay your share from Activity.",
            link="/ride/activity/",
        )
    return splits


def _own_split(split: FareSplit, user) -> FareSplit:
    split = (
        FareSplit.objects.select_for_update().select_related("trip__rider__user").get(pk=split.pk)
    )
    if not (user.is_rider and split.friend.user_id == user.pk):
        raise ActionNotPermitted("This request isn't yours.")
    if split.status != FareSplitStatus.REQUESTED:
        raise InvalidStateTransition("This request is already closed.")
    return split


@transaction.atomic
def pay_split(split: FareSplit, *, user, method: str, payer_reference: str = "") -> FareSplit:
    from apps.payments import accounts
    from apps.payments.models import PaymentMethod, PaymentPurpose, PaymentStatus, TransactionKind
    from apps.payments.services import ensure_wallet, gateway_charge, post, wallet_balance

    split = _own_split(split, user)
    trip = split.trip
    if method == PaymentMethod.WALLET:
        if wallet_balance(user) < split.amount:
            raise BusinessRuleViolation("Not enough wallet balance.", field="method")
        source = ensure_wallet(user)
    elif method in (PaymentMethod.UPI, PaymentMethod.CARD):
        payment, _ = gateway_charge(
            user=user,
            amount=split.amount,
            method=method,
            purpose=PaymentPurpose.SPLIT,
            trip=trip,
            payer_reference=payer_reference,
        )
        if payment.status != PaymentStatus.SUCCEEDED:
            raise BusinessRuleViolation(f"Payment failed: {payment.failure_reason}")
        source = accounts.GATEWAY
    else:
        raise BusinessRuleViolation("Pay with UPI, card or your wallet.", field="method")
    post(
        TransactionKind.FARE_SPLIT,
        [(source, -split.amount), (ensure_wallet(trip.rider.user), split.amount)],
        trip=trip,
        description=f"{user.get_full_name() or 'Friend'}'s share of {trip.trip_number}",
    )
    split.status = FareSplitStatus.PAID
    split.payment_method = method
    split.responded_at = timezone.now()
    split.save(update_fields=["status", "payment_method", "responded_at"])
    notify(
        trip.rider.user,
        f"{user.first_name or 'Your friend'} paid their share: ₹{split.amount}",
        "It's in your Ride Pulse wallet.",
        level=Level.SUCCESS,
        link="/ride/wallet/",
    )
    return split


@transaction.atomic
def decline_split(split: FareSplit, *, user) -> FareSplit:
    split = _own_split(split, user)
    split.status = FareSplitStatus.DECLINED
    split.responded_at = timezone.now()
    split.save(update_fields=["status", "responded_at"])
    notify(split.trip.rider.user, f"{user.first_name or 'Your friend'} declined to split the fare")
    return split


@transaction.atomic
def cancel_split(split: FareSplit, *, user) -> FareSplit:
    split = FareSplit.objects.select_for_update().select_related("trip__rider").get(pk=split.pk)
    if split.trip.rider.user_id != user.pk:
        raise ActionNotPermitted("Only the rider who asked can cancel this request.")
    if split.status != FareSplitStatus.REQUESTED:
        raise InvalidStateTransition("Only unpaid requests can be cancelled.")
    split.status = FareSplitStatus.CANCELLED
    split.responded_at = timezone.now()
    split.save(update_fields=["status", "responded_at"])
    return split
