"""Money movement, recorded with double-entry bookkeeping.

Every financial event is a ``LedgerTransaction`` whose entries sum to exactly zero, and wallet
balances change only through those entries. ``verify_ledger()`` re-checks both invariants
straight from the database.

Trip settlement, where the rider pays T = driver earning D + commission C + fees F − promo P +
GST G::

    UPI/card   gateway −T   driver +D   commission +C   fees +F   promotions −P   GST +G
    wallet     rider −T     driver +D   ...same platform legs
    cash       driver −(T − D)          ...same platform legs   (the driver holds T in cash
                                                                  and owes the platform's share)
"""

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.core.conf import payout_minimum, platform_commission_percent, referral_bonus
from apps.core.dates import week_start
from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.core.money import ZERO, money
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from . import accounts, gateway, razorpay
from .models import (
    ONLINE_METHODS,
    LedgerEntry,
    LedgerTransaction,
    Payment,
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    Payout,
    PayoutStatus,
    TransactionKind,
    Wallet,
)

MIN_TOP_UP = Decimal(50)
MAX_TOP_UP = Decimal(10_000)
MIN_TIP = Decimal(10)
MAX_TIP = Decimal(500)

Leg = tuple["Wallet | str", Decimal]

logger = logging.getLogger(__name__)


class UnbalancedTransaction(Exception):
    pass


# --- Ledger core -------------------------------------------------------------------------


def ensure_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def wallet_balance(user) -> Decimal:
    balance = Wallet.objects.filter(user=user).values_list("balance", flat=True).first()
    return balance if balance is not None else ZERO


@transaction.atomic
def post(
    kind: str,
    legs: Iterable[Leg],
    *,
    trip=None,
    description: str = "",
    actor=None,
    at: datetime | None = None,
) -> LedgerTransaction:
    """Record a balanced transaction and apply its wallet legs atomically."""
    legs = [(target, money(amount)) for target, amount in legs if money(amount) != 0]
    if sum((amount for _, amount in legs), ZERO) != 0:
        raise UnbalancedTransaction(f"{kind} legs sum to {sum(a for _, a in legs)}")
    at = at or timezone.now()
    txn = LedgerTransaction.objects.create(
        reference=next_reference("TXN", year=at.year, width=8),
        kind=kind,
        trip=trip,
        description=description[:255],
        created_by=actor,
        created_at=at,
    )
    entries = []
    for target, amount in legs:
        if isinstance(target, Wallet):
            entries.append(
                LedgerEntry(transaction=txn, account=target.account, wallet=target, amount=amount)
            )
            # Atomic in-database increment: concurrent postings can't lose an update.
            Wallet.objects.filter(pk=target.pk).update(balance=F("balance") + amount)
        else:
            entries.append(LedgerEntry(transaction=txn, account=target, amount=amount))
    LedgerEntry.objects.bulk_create(entries)
    return txn


def verify_ledger() -> dict:
    """Integrity check: every transaction balances and every wallet equals its entries."""
    unbalanced = list(
        LedgerEntry.objects.values("transaction_id")
        .annotate(total=Sum("amount"))
        .exclude(total=0)
        .values_list("transaction_id", flat=True)
    )
    mismatched = [
        w.pk
        for w in Wallet.objects.annotate(ledger_total=Sum("entries__amount", default=ZERO)).exclude(
            balance=F("ledger_total")
        )
    ]
    return {
        "balanced": not unbalanced and not mismatched,
        "unbalanced_transactions": unbalanced,
        "mismatched_wallets": mismatched,
    }


def account_balances() -> dict[str, Decimal]:
    rows = (
        LedgerEntry.objects.filter(account__in=accounts.PLATFORM_ACCOUNTS)
        .values("account")
        .annotate(total=Sum("amount"))
    )
    balances = dict.fromkeys(accounts.PLATFORM_ACCOUNTS, ZERO)
    balances.update({r["account"]: r["total"] for r in rows})
    return balances


# --- Gateway -----------------------------------------------------------------------------


def gateway_charge(
    *,
    user,
    amount: Decimal,
    method: str,
    purpose: str,
    trip=None,
    idempotency_key: str = "",
    payer_reference: str = "",
) -> tuple[Payment, bool]:
    """Charge through the gateway. Returns ``(payment, created)``; a retried idempotency key
    returns the original payment instead of charging twice."""
    if method not in ONLINE_METHODS:
        raise BusinessRuleViolation("Choose UPI or card for online payments.", field="method")
    if idempotency_key:
        existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.user_id != user.pk or existing.amount != money(amount):
                raise ConflictError("This idempotency key was already used for another payment.")
            return existing, False
    try:
        result = gateway.charge(money(amount), method=method, payer_reference=payer_reference)
    except Exception:  # gateway down or timing out: a failed payment, not a crashed request
        logger.exception("Payment gateway unavailable")
        result = gateway.GatewayResult(
            succeeded=False, reference="", failure_reason="Payment gateway unavailable, try again."
        )
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                reference=next_reference("PAY", year=timezone.now().year, width=8),
                user=user,
                trip=trip,
                purpose=purpose,
                method=method,
                amount=money(amount),
                status=PaymentStatus.SUCCEEDED if result.succeeded else PaymentStatus.FAILED,
                gateway_reference=result.reference,
                failure_reason=result.failure_reason,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:  # a concurrent retry with the same key won the race
        return Payment.objects.get(idempotency_key=idempotency_key), False
    return payment, True


# --- Trips -------------------------------------------------------------------------------


def _platform_legs(fare) -> list[Leg]:
    return [
        (accounts.PLATFORM_COMMISSION, fare.platform_commission),
        (accounts.PLATFORM_FEES, fare.fees),
        (accounts.GST_PAYABLE, fare.gst),
        (accounts.PLATFORM_PROMOTIONS, -fare.discount),
    ]


@transaction.atomic
def settle_trip(trip, *, payer_reference: str = "", now: datetime | None = None) -> str:
    """Collect the fare for a completed trip and split it. Returns the trip payment status."""
    from apps.rides.models import TripPaymentStatus

    fare = trip.final_fare
    total = fare.total
    # A family/business profile pays from its owner's wallet (and owes any shortfall).
    payer = trip.payment_profile.owner.user if trip.payment_profile_id else trip.rider.user
    rider_wallet = ensure_wallet(payer)
    driver_wallet = ensure_wallet(trip.driver.user)
    platform = _platform_legs(fare)
    description = f"Fare for {trip.trip_number}"

    if trip.payment_method == PaymentMethod.CASH:
        post(
            TransactionKind.TRIP_FARE,
            [(driver_wallet, fare.driver_earning - total), *platform],
            trip=trip,
            description=description + " (cash collected by driver)",
            at=now,
        )
        return TripPaymentStatus.PAID

    credit = trip.payment_profile.credit_limit if trip.payment_profile_id else 0
    if trip.payment_method == PaymentMethod.WALLET and rider_wallet.balance + credit >= total:
        post(
            TransactionKind.TRIP_FARE,
            [(rider_wallet, -total), (driver_wallet, fare.driver_earning), *platform],
            trip=trip,
            description=description,
            at=now,
        )
        return TripPaymentStatus.PAID

    if trip.payment_method in ONLINE_METHODS:
        payment, _ = gateway_charge(
            user=trip.rider.user,
            amount=total,
            method=trip.payment_method,
            purpose=PaymentPurpose.TRIP,
            trip=trip,
            idempotency_key=f"trip-{trip.pk}-fare",
            payer_reference=payer_reference,
        )
        if payment.status == PaymentStatus.SUCCEEDED:
            post(
                TransactionKind.TRIP_FARE,
                [(accounts.GATEWAY, -total), (driver_wallet, fare.driver_earning), *platform],
                trip=trip,
                description=description,
                at=now,
            )
            return TripPaymentStatus.PAID

    # Payment failed or the wallet was short: the driver is still paid, and the rider owes the
    # fare as dues that must be cleared before their next booking.
    post(
        TransactionKind.TRIP_FARE,
        [(rider_wallet, -total), (driver_wallet, fare.driver_earning), *platform],
        trip=trip,
        description=description + " (unpaid, added to rider dues)",
        at=now,
    )
    notify(
        payer,
        "Payment pending for your last ride",
        f"₹{total} is due. Clear it from your wallet before your next booking.",
        level=Level.WARNING,
        link="/ride/wallet/",
    )
    return TripPaymentStatus.DUES


@transaction.atomic
def charge_cancellation_fee(trip, fee: Decimal, *, now: datetime | None = None) -> None:
    """Charged to the rider's wallet (as dues if it goes negative). The driver who drove to the
    pickup keeps the fee minus commission."""
    fee = money(fee)
    if fee <= 0:
        return
    rider_wallet = ensure_wallet(trip.rider.user)
    legs: list[Leg] = [(rider_wallet, -fee)]
    if trip.driver_id:
        driver_share = money(fee * (100 - platform_commission_percent()) / 100)
        legs += [
            (ensure_wallet(trip.driver.user), driver_share),
            (accounts.PLATFORM_COMMISSION, fee - driver_share),
        ]
    else:
        legs.append((accounts.PLATFORM_FEES, fee))
    post(
        TransactionKind.CANCELLATION_FEE,
        legs,
        trip=trip,
        description=f"Cancellation fee for {trip.trip_number}",
        at=now,
    )


@transaction.atomic
def add_tip(
    trip, *, amount: Decimal, method: str, idempotency_key: str = "", payer_reference: str = ""
) -> LedgerTransaction:
    amount = money(amount)
    if not MIN_TIP <= amount <= MAX_TIP:
        raise BusinessRuleViolation(
            f"Tips must be between ₹{MIN_TIP} and ₹{MAX_TIP}.", field="amount"
        )
    driver_wallet = ensure_wallet(trip.driver.user)
    rider_wallet = ensure_wallet(trip.rider.user)
    if method == PaymentMethod.WALLET:
        if rider_wallet.balance < amount:
            raise BusinessRuleViolation("Not enough wallet balance for this tip.", field="amount")
        source: Wallet | str = rider_wallet
    else:
        payment, _ = gateway_charge(
            user=trip.rider.user,
            amount=amount,
            method=method,
            purpose=PaymentPurpose.TIP,
            trip=trip,
            idempotency_key=idempotency_key,
            payer_reference=payer_reference,
        )
        if payment.status != PaymentStatus.SUCCEEDED:
            raise BusinessRuleViolation(f"Payment failed: {payment.failure_reason}")
        source = accounts.GATEWAY
    txn = post(
        TransactionKind.TIP,
        [(source, -amount), (driver_wallet, amount)],
        trip=trip,
        description=f"Tip for {trip.trip_number}",
    )
    notify(
        trip.driver.user,
        f"You received a ₹{amount} tip",
        f"From your rider on {trip.trip_number}. Tips go 100% to you.",
        level=Level.SUCCESS,
    )
    return txn


@transaction.atomic
def refund_to_wallet(trip, amount: Decimal, *, reason: str, actor=None) -> LedgerTransaction:
    amount = money(amount)
    already = LedgerEntry.objects.filter(
        transaction__trip=trip, transaction__kind=TransactionKind.REFUND, wallet__isnull=False
    ).aggregate(total=Sum("amount", default=ZERO))["total"]
    refundable = (trip.fare_total or ZERO) - already
    if amount <= 0 or amount > refundable:
        raise BusinessRuleViolation(f"You can refund at most ₹{refundable}.", field="amount")
    txn = post(
        TransactionKind.REFUND,
        [(accounts.PLATFORM_REFUNDS, -amount), (ensure_wallet(trip.rider.user), amount)],
        trip=trip,
        description=f"Refund for {trip.trip_number}: {reason}",
        actor=actor,
    )
    from apps.reliability.outbox import emit

    emit(
        "payment.refunded",
        {
            "trip_id": trip.pk,
            "trip_number": trip.trip_number,
            "amount": amount,
            "reason": reason,
            "payment_profile_id": trip.payment_profile_id,
        },
        aggregate=f"trip:{trip.pk}",
    )
    notify(
        trip.rider.user,
        f"₹{amount} refunded to your wallet",
        reason,
        level=Level.SUCCESS,
        link="/ride/wallet/",
        email=True,
    )
    return txn


# --- Referrals ---------------------------------------------------------------------------


@transaction.atomic
def grant_referral_bonus(rider, *, now: datetime | None = None) -> LedgerTransaction | None:
    """Pay the referral bonus to a new rider and whoever invited them, once, after the new
    rider's first completed trip. Funded by the platform's promotions budget."""
    from apps.riders.models import RiderProfile

    rider = RiderProfile.objects.select_for_update().select_related("user").get(pk=rider.pk)
    if rider.referred_by_id is None or rider.referral_rewarded_at or rider.completed_trips < 1:
        return None
    referrer = RiderProfile.objects.select_related("user").get(pk=rider.referred_by_id)
    bonus = referral_bonus()
    now = now or timezone.now()
    txn = post(
        TransactionKind.REFERRAL_BONUS,
        [
            (accounts.PLATFORM_PROMOTIONS, -2 * bonus),
            (ensure_wallet(referrer.user), bonus),
            (ensure_wallet(rider.user), bonus),
        ],
        description=f"Referral: {referrer.referral_code} invited {rider.user.email}",
        at=now,
    )
    RiderProfile.objects.filter(pk=rider.pk).update(referral_rewarded_at=now)
    notify(
        referrer.user,
        f"You earned ₹{bonus}!",
        f"{rider.user.first_name or 'Your friend'} took their first ride. "
        f"₹{bonus} is in your wallet.",
        level=Level.SUCCESS,
        link="/ride/wallet/",
    )
    notify(
        rider.user,
        f"₹{bonus} referral bonus added",
        "Thanks for riding with a friend's invite. The bonus is in your wallet.",
        level=Level.SUCCESS,
        link="/ride/wallet/",
    )
    return txn


# --- Wallets -----------------------------------------------------------------------------


@transaction.atomic
def top_up(
    user, amount: Decimal, *, method: str, idempotency_key: str = "", payer_reference: str = ""
) -> Payment:
    amount = money(amount)
    if not MIN_TOP_UP <= amount <= MAX_TOP_UP:
        raise BusinessRuleViolation(
            f"Top up between ₹{MIN_TOP_UP} and ₹{MAX_TOP_UP:,}.", field="amount"
        )
    payment, created = gateway_charge(
        user=user,
        amount=amount,
        method=method,
        purpose=PaymentPurpose.TOP_UP,
        idempotency_key=idempotency_key,
        payer_reference=payer_reference,
    )
    if created and payment.status == PaymentStatus.SUCCEEDED:
        post(
            TransactionKind.TOP_UP,
            [(accounts.GATEWAY, -amount), (ensure_wallet(user), amount)],
            description=f"Top-up {payment.reference}",
        )
    return payment


def start_razorpay_top_up(user, amount: Decimal) -> Payment:
    """Create a Razorpay order for a wallet top-up; the wallet is credited once it's paid."""
    from apps.reliability.fallbacks import CASH_ONLY, active

    if CASH_ONLY in active():
        raise BusinessRuleViolation("Online payments are down right now. Please try again later.")
    if not razorpay.enabled():
        raise BusinessRuleViolation("Online checkout isn't configured.")
    amount = money(amount)
    if not MIN_TOP_UP <= amount <= MAX_TOP_UP:
        raise BusinessRuleViolation(
            f"Top up between ₹{MIN_TOP_UP} and ₹{MAX_TOP_UP:,}.", field="amount"
        )
    reference = next_reference("PAY", year=timezone.now().year, width=8)
    try:
        order_id = razorpay.create_order(
            amount, receipt=reference, notes={"user": str(user.pk), "purpose": "TOP_UP"}
        )
    except razorpay.RazorpayError as exc:
        raise BusinessRuleViolation("The payment gateway is unavailable. Try again.") from exc
    return Payment.objects.create(
        reference=reference,
        user=user,
        purpose=PaymentPurpose.TOP_UP,
        method=PaymentMethod.UPI,
        amount=amount,
        status=PaymentStatus.PENDING,
        gateway_order_id=order_id,
    )


@transaction.atomic
def complete_razorpay_top_up(
    *, order_id: str, payment_id: str, signature: str = "", user=None, verified: bool = False
) -> Payment:
    """Credit the wallet for a paid Razorpay order. Called by the browser (with Checkout's
    signature) and by the webhook (already verified); whichever comes first wins, the other is
    a no-op."""
    payment = (
        Payment.objects.select_for_update()
        .filter(gateway_order_id=order_id, purpose=PaymentPurpose.TOP_UP)
        .first()
    )
    if payment is None or (user is not None and payment.user_id != user.pk):
        raise BusinessRuleViolation("Unknown payment.")
    if payment.status == PaymentStatus.SUCCEEDED:
        return payment
    if not verified and not razorpay.payment_signature_valid(order_id, payment_id, signature):
        raise BusinessRuleViolation("The payment couldn't be verified.")
    payment.status = PaymentStatus.SUCCEEDED
    payment.gateway_reference = payment_id[:40]
    payment.save(update_fields=["status", "gateway_reference", "updated_at"])
    post(
        TransactionKind.TOP_UP,
        [(accounts.GATEWAY, -payment.amount), (ensure_wallet(payment.user), payment.amount)],
        description=f"Top-up {payment.reference} (Razorpay {payment_id})",
    )
    notify(
        payment.user,
        f"₹{payment.amount} added to your wallet",
        level=Level.SUCCESS,
        link="/ride/wallet/",
    )
    return payment


@transaction.atomic
def pay_dues(user, *, method: str, idempotency_key: str = "", payer_reference: str = "") -> Payment:
    balance = wallet_balance(user)
    if balance >= 0:
        raise BusinessRuleViolation("There are no dues to pay.")
    amount = -balance
    payment, created = gateway_charge(
        user=user,
        amount=amount,
        method=method,
        purpose=PaymentPurpose.DUES,
        idempotency_key=idempotency_key,
        payer_reference=payer_reference,
    )
    if created and payment.status == PaymentStatus.SUCCEEDED:
        post(
            TransactionKind.DUES_PAYMENT,
            [(accounts.GATEWAY, -amount), (ensure_wallet(user), amount)],
            description=f"Dues cleared {payment.reference}",
        )
        _mark_unpaid_trips_paid(user)
    return payment


def _mark_unpaid_trips_paid(user) -> None:
    """Dues are a rider's unpaid fares: once cleared, those trips are paid, and their invoices
    can finally go out."""
    from apps.rides import invoices
    from apps.rides.models import Trip, TripPaymentStatus

    if not user.is_rider:
        return
    trips = list(Trip.objects.filter(rider__user=user, payment_status=TripPaymentStatus.DUES))
    Trip.objects.filter(pk__in=[t.pk for t in trips]).update(
        payment_status=TripPaymentStatus.PAID, updated_at=timezone.now()
    )
    for trip in trips:
        trip.payment_status = TripPaymentStatus.PAID
        invoices.send_after_commit(trip)


def wallet_statement(user, *, limit: int = 50):
    return (
        LedgerEntry.objects.filter(wallet__user=user)
        .select_related("transaction", "transaction__trip")
        .order_by("-transaction__created_at", "-id")[:limit]
    )


# --- Payouts -----------------------------------------------------------------------------


@transaction.atomic
def create_weekly_payouts(*, now: datetime | None = None) -> list[Payout]:
    """Moves each driver's positive balance (above the minimum) to their bank account."""
    from apps.drivers.models import DriverProfile

    now = now or timezone.now()
    from apps.drivers import loans

    loans.collect(now=now)  # vehicle-loan EMIs come out first (drivers keep a minimum)
    period_end = week_start(timezone.localdate(now)) - timedelta(days=1)
    period_start = period_end - timedelta(days=6)
    # Non-null ids only: NOT IN over a list containing NULL matches nothing in SQL.
    pending = Payout.objects.filter(status=PayoutStatus.PENDING, driver__isnull=False).values(
        "driver_id"
    )
    wallets = (
        Wallet.objects.select_for_update()
        .filter(user__driver_profile__isnull=False, balance__gte=payout_minimum())
        .exclude(user__driver_profile__in=pending)
    )
    payouts = []
    for wallet in wallets:
        driver = DriverProfile.objects.get(user_id=wallet.user_id)
        payout = Payout.objects.create(
            payout_number=next_reference("PO", year=period_end.year),
            driver=driver,
            amount=wallet.balance,
            period_start=period_start,
            period_end=period_end,
        )
        payouts.append(_send_payout(payout, wallet, now))
    payouts += _fleet_owner_payouts(period_start, period_end, now)
    return payouts


def _fleet_owner_payouts(period_start, period_end, now) -> list[Payout]:
    """Fleet owners get their share of their drivers' earnings on the same weekly run."""
    pending = Payout.objects.filter(status=PayoutStatus.PENDING, fleet_owner__isnull=False).values(
        "fleet_owner_id"
    )
    wallets = (
        Wallet.objects.select_for_update()
        .filter(user__fleet_owner__isnull=False, balance__gte=payout_minimum())
        .exclude(user__fleet_owner__in=pending)
        .select_related("user__fleet_owner")
    )
    payouts = []
    for wallet in wallets:
        payout = Payout.objects.create(
            payout_number=next_reference("PO", year=period_end.year),
            fleet_owner=wallet.user.fleet_owner,
            amount=wallet.balance,
            period_start=period_start,
            period_end=period_end,
        )
        payouts.append(_send_payout(payout, wallet, now))
    return payouts


def _send_payout(payout: Payout, wallet: Wallet, now) -> Payout:
    from apps.reliability.outbox import emit

    emit(
        "payout.created",
        {
            "payout_number": payout.payout_number,
            "amount": payout.amount,
            "driver_id": payout.driver_id,
            "fleet_owner_id": payout.fleet_owner_id,
            "period_start": payout.period_start,
            "period_end": payout.period_end,
        },
        aggregate=f"payout:{payout.pk}",
        at=now,
    )
    post(
        TransactionKind.PAYOUT,
        [(wallet, -payout.amount), (accounts.PAYOUTS_IN_TRANSIT, payout.amount)],
        description=f"Payout {payout.payout_number}",
        at=now,
    )
    notify(
        payout.payee,
        f"Payout of ₹{payout.amount} is on its way",
        f"Earnings for {payout.period_start:%d %b} – {payout.period_end:%d %b}.",
        level=Level.SUCCESS,
        link="/drive/earnings/" if payout.driver_id else "/fleet",
    )
    return payout


@transaction.atomic
def mark_payout_paid(payout: Payout, *, bank_reference: str, actor=None) -> Payout:
    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status != PayoutStatus.PENDING:
        raise BusinessRuleViolation("Only processing payouts can be marked paid.")
    payout.status = PayoutStatus.PAID
    payout.bank_reference = bank_reference
    payout.paid_at = timezone.now()
    payout.save(update_fields=["status", "bank_reference", "paid_at", "updated_at"])
    return payout


@transaction.atomic
def mark_payout_failed(payout: Payout, *, reason: str, actor=None) -> Payout:
    """The bank rejected the transfer: the money goes back into the driver's wallet."""
    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status != PayoutStatus.PENDING:
        raise BusinessRuleViolation("Only processing payouts can fail.")
    payout.status = PayoutStatus.FAILED
    payout.failure_reason = reason
    payout.save(update_fields=["status", "failure_reason", "updated_at"])
    post(
        TransactionKind.PAYOUT_REVERSAL,
        [
            (accounts.PAYOUTS_IN_TRANSIT, -payout.amount),
            (ensure_wallet(payout.payee), payout.amount),
        ],
        description=f"Payout {payout.payout_number} failed: {reason}",
        actor=actor,
    )
    notify(
        payout.payee,
        "Your payout failed",
        f"{reason} The amount is back in your wallet.",
        level=Level.DANGER,
        email=True,
    )
    return payout


def driver_earnings(driver, *, start: datetime, end: datetime) -> dict:
    from apps.rides.models import Trip, TripStatus

    trips = Trip.objects.filter(
        driver=driver, status=TripStatus.COMPLETED, completed_at__gte=start, completed_at__lt=end
    )
    totals = trips.aggregate(
        fares=Sum("fare_total", default=ZERO),
        earnings=Sum("driver_earning", default=ZERO),
        tips=Sum("tip_amount", default=ZERO),
        commission=Sum("platform_commission", default=ZERO),
        distance=Sum("actual_distance_km", default=ZERO),
    )
    cash = trips.filter(payment_method=PaymentMethod.CASH).aggregate(
        total=Sum("fare_total", default=ZERO)
    )["total"]
    cancellation = LedgerEntry.objects.filter(
        wallet__user=driver.user,
        transaction__kind=TransactionKind.CANCELLATION_FEE,
        transaction__created_at__gte=start,
        transaction__created_at__lt=end,
    ).aggregate(total=Sum("amount", default=ZERO))["total"]
    return {
        "trips": trips.count(),
        "fares": totals["fares"],
        "earnings": totals["earnings"] + totals["tips"] + cancellation,
        "trip_earnings": totals["earnings"],
        "tips": totals["tips"],
        "cancellation_fees": cancellation,
        "commission": totals["commission"],
        "cash_collected": cash,
        "distance_km": totals["distance"],
    }
