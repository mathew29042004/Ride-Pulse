from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Cash"
    UPI = "UPI", "UPI"
    CARD = "CARD", "Card"
    WALLET = "WALLET", "Ride Pulse wallet"


ONLINE_METHODS = (PaymentMethod.UPI, PaymentMethod.CARD)


class Wallet(TimeStampedModel):
    """A rider's or driver's balance. It is only ever changed by ledger postings.

    Riders can go negative only through unpaid fares or cancellation fees ("dues"); drivers go
    negative when they collect cash and owe the platform its commission.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"Wallet of {self.user} (₹{self.balance})"

    @property
    def account(self) -> str:
        return f"wallet:{self.user_id}"


class TransactionKind(models.TextChoices):
    TRIP_FARE = "TRIP_FARE", "Trip fare"
    CANCELLATION_FEE = "CANCELLATION_FEE", "Cancellation fee"
    TIP = "TIP", "Tip"
    TOP_UP = "TOP_UP", "Wallet top-up"
    DUES_PAYMENT = "DUES_PAYMENT", "Dues payment"
    PAYOUT = "PAYOUT", "Driver payout"
    PAYOUT_REVERSAL = "PAYOUT_REVERSAL", "Payout reversal"
    REFUND = "REFUND", "Refund"
    REFERRAL_BONUS = "REFERRAL_BONUS", "Referral bonus"
    RIDE_PASS = "RIDE_PASS", "Ride Pass purchase"
    FARE_SPLIT = "FARE_SPLIT", "Fare split share"
    DRIVER_BONUS = "DRIVER_BONUS", "Driver goal bonus"
    FARE_LOCK = "FARE_LOCK", "Fare Lock purchase"
    DRIVER_PASS = "DRIVER_PASS", "Driver day pass"
    ECO_REWARD = "ECO_REWARD", "Eco points reward"
    TDS = "TDS", "Income tax withheld (TDS)"
    INCENTIVE = "INCENTIVE", "Driver incentive"
    FLEET_SHARE = "FLEET_SHARE", "Fleet owner share"


class LedgerTransaction(models.Model):
    """A balanced set of ledger entries: the amounts of its entries always sum to zero."""

    reference = models.CharField(max_length=24, unique=True)
    kind = models.CharField(max_length=16, choices=TransactionKind.choices)
    trip = models.ForeignKey(
        "rides.Trip",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_transactions",
    )
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["kind", "-created_at"], name="ledger_txn_kind_idx")]

    def __str__(self) -> str:
        return self.reference


class LedgerEntry(models.Model):
    """One leg of a transaction. Positive amounts flow into the account, negative out of it."""

    transaction = models.ForeignKey(
        LedgerTransaction, on_delete=models.CASCADE, related_name="entries"
    )
    account = models.CharField(max_length=40)
    wallet = models.ForeignKey(
        Wallet, null=True, blank=True, on_delete=models.PROTECT, related_name="entries"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["account"], name="ledger_entry_account_idx"),
            models.Index(fields=["wallet", "transaction"], name="ledger_entry_wallet_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(amount=0), name="ledger_entry_non_zero"),
        ]

    def __str__(self) -> str:
        return f"{self.account} {self.amount:+}"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"  # a Razorpay order waiting for the rider to pay
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"


class PaymentPurpose(models.TextChoices):
    TRIP = "TRIP", "Trip fare"
    TIP = "TIP", "Tip"
    TOP_UP = "TOP_UP", "Wallet top-up"
    DUES = "DUES", "Dues payment"
    PASS = "PASS", "Ride Pass"
    SPLIT = "SPLIT", "Fare split"
    LOCK = "LOCK", "Fare Lock"


class Payment(TimeStampedModel):
    """A charge attempt at the payment gateway (UPI or card)."""

    reference = models.CharField(max_length=24, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    purpose = models.CharField(max_length=8, choices=PaymentPurpose.choices)
    method = models.CharField(max_length=6, choices=PaymentMethod.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=9, choices=PaymentStatus.choices)
    gateway_reference = models.CharField(max_length=40, blank=True)
    gateway_order_id = models.CharField(max_length=40, blank=True, db_index=True)
    failure_reason = models.CharField(max_length=160, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Clients retry with the same key; the database guarantees a single charge.
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="payment_idempotency_key_unique",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self) -> str:
        return self.reference


class PayoutStatus(models.TextChoices):
    PENDING = "PENDING", "Processing"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class Payout(TimeStampedModel):
    @property
    def payee(self):
        return self.driver.user if self.driver_id else self.fleet_owner.user

    @property
    def payee_name(self) -> str:
        return self.driver.name if self.driver_id else self.fleet_owner.company_name

    payout_number = models.CharField(max_length=24, unique=True)
    # Paid to a driver, or to a fleet owner (their share of their drivers' earnings).
    driver = models.ForeignKey(
        "drivers.DriverProfile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    fleet_owner = models.ForeignKey(
        "fleet.FleetOwner", null=True, blank=True, on_delete=models.PROTECT, related_name="payouts"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=7, choices=PayoutStatus.choices, default=PayoutStatus.PENDING
    )
    bank_reference = models.CharField(max_length=40, blank=True)
    failure_reason = models.CharField(max_length=160, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payout_amount_positive"),
            models.UniqueConstraint(
                fields=["driver"],
                condition=Q(status="PENDING"),
                name="one_pending_payout_per_driver",
            ),
            models.UniqueConstraint(
                fields=["fleet_owner"],
                condition=Q(status="PENDING"),
                name="one_pending_payout_per_fleet_owner",
            ),
            models.CheckConstraint(
                condition=Q(driver__isnull=False, fleet_owner__isnull=True)
                | Q(driver__isnull=True, fleet_owner__isnull=False),
                name="payout_has_one_payee",
            ),
        ]

    def __str__(self) -> str:
        return self.payout_number
