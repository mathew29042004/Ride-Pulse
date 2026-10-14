"""Fare Lock: "lock today's price for my commute".

From a finished trip the rider locks that route and ride type at its *normal* price (no surge)
for a week, on chosen weekdays, within an hour of the same time of day, for a small fee. Any
booking that matches (pickup and drop within 400 m, same ride type, inside the window) is priced
at no more than the locked fare; Ride Pulse pays the difference as a discount, so the driver
earns exactly what they normally would.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.conf import fare_lock_terms
from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.geo.distance import haversine_km
from apps.notifications.models import Level
from apps.notifications.services import notify

from .fare import FareBreakdown, with_platform_discount
from .models import FareLock

LOCK_CODE = "FARE_LOCK"
WEEKDAYS = [0, 1, 2, 3, 4]


def _minute_of_day(at: datetime) -> int:
    local = timezone.localtime(at)
    return local.hour * 60 + local.minute


def normal_price(trip) -> Decimal:
    """The route's price without surge, promo, boost or pass: what gets locked."""
    from apps.pricing import services as pricing

    estimate = pricing.estimate_fare(
        city=trip.city,
        ride_type=trip.ride_type,
        pickup=(trip.pickup_lat, trip.pickup_lng),
        dropoff=(trip.dropoff_lat, trip.dropoff_lng),
    )
    fare = pricing.price_trip(
        city=trip.city,
        ride_type=trip.ride_type,
        route=estimate.route,
        surge_multiplier=Decimal(1),
        airport=False,
    )
    return fare.total


@transaction.atomic
def lock_from_trip(
    trip, *, user, method: str, weekdays=None, payer_reference: str = "", now=None
) -> FareLock:
    from apps.payments import accounts
    from apps.payments.models import PaymentMethod, PaymentPurpose, PaymentStatus, TransactionKind
    from apps.payments.services import ensure_wallet, gateway_charge, post, wallet_balance
    from apps.rides.models import TripStatus

    now = now or timezone.now()
    if trip.rider.user_id != user.pk:
        raise BusinessRuleViolation("Only the rider can lock this fare.")
    if trip.status != TripStatus.COMPLETED or trip.service != "RIDE":
        raise InvalidStateTransition("Lock a fare from a completed ride.")
    weekdays = sorted({int(d) for d in (weekdays or WEEKDAYS) if 0 <= int(d) <= 6})
    if not weekdays:
        raise BusinessRuleViolation("Choose at least one day.", field="weekdays")
    terms = fare_lock_terms()
    fee = terms["fee"]
    rider = trip.rider
    if method == PaymentMethod.WALLET:
        if wallet_balance(user) < fee:
            raise BusinessRuleViolation("Not enough wallet balance.", field="method")
        source = ensure_wallet(user)
    elif method in (PaymentMethod.UPI, PaymentMethod.CARD):
        payment, _ = gateway_charge(
            user=user,
            amount=fee,
            method=method,
            purpose=PaymentPurpose.LOCK,
            payer_reference=payer_reference,
        )
        if payment.status != PaymentStatus.SUCCEEDED:
            raise BusinessRuleViolation(f"Payment failed: {payment.failure_reason}")
        source = accounts.GATEWAY
    else:
        raise BusinessRuleViolation("Pay with UPI, card or your wallet.", field="method")
    reference = next_reference("LOCK", year=now.year, width=6)
    post(
        TransactionKind.FARE_LOCK,
        [(source, -fee), (accounts.PLATFORM_SUBSCRIPTIONS, fee)],
        description=f"Fare Lock {reference}",
        at=now,
    )
    lock = FareLock.objects.create(
        rider=rider,
        ride_type=trip.ride_type,
        pickup_lat=trip.pickup_lat,
        pickup_lng=trip.pickup_lng,
        pickup_address=trip.pickup_address,
        dropoff_lat=trip.dropoff_lat,
        dropoff_lng=trip.dropoff_lng,
        dropoff_address=trip.dropoff_address,
        depart_minute=_minute_of_day(trip.requested_at),
        weekdays=weekdays,
        locked_total=normal_price(trip),
        fee=fee,
        starts_at=now,
        ends_at=now + timedelta(days=terms["days"]),
        reference=reference,
    )
    notify(
        user,
        f"Fare locked at ₹{lock.locked_total}",
        f"{lock.pickup_address} → {lock.dropoff_address}, around "
        f"{timezone.localtime(trip.requested_at):%I:%M %p} on your chosen days, for "
        f"{terms['days']} days. Surge won't apply.",
        level=Level.SUCCESS,
        link="/ride/account",
    )
    return lock


def matching_lock(rider, ride_type, pickup, dropoff, at: datetime) -> FareLock | None:
    if rider is None:
        return None
    terms = fare_lock_terms()
    local = timezone.localtime(at)
    minute = _minute_of_day(at)
    near = terms["match_meters"] / 1000
    for lock in rider.fare_locks.filter(
        ride_type=ride_type, starts_at__lte=at, ends_at__gt=at, weekdays__contains=[local.weekday()]
    ):
        gap = min(abs(minute - lock.depart_minute), 1440 - abs(minute - lock.depart_minute))
        if (
            gap <= terms["window_minutes"]
            and haversine_km(lock.pickup_lat, lock.pickup_lng, *pickup) <= near
            and haversine_km(lock.dropoff_lat, lock.dropoff_lng, *dropoff) <= near
        ):
            return lock
    return None


def apply(fare: FareBreakdown, lock: FareLock | None) -> FareBreakdown:
    """Cap the fare at the locked price (Ride Pulse pays the rest)."""
    if lock is None or fare.total <= lock.locked_total:
        return fare
    return with_platform_discount(
        fare, LOCK_CODE, "Fare Lock (price locked)", fare.total - lock.locked_total
    )


def record_use(lock: FareLock, saved: Decimal) -> None:
    FareLock.objects.filter(pk=lock.pk).update(uses=F("uses") + 1, saved=F("saved") + saved)
