"""Zero-commission day pass (the Namma Yatri / Rapido model): instead of a cut of every fare,
the driver pays a small flat fee for the day (by vehicle) and keeps 100% of every fare. Riders
pay exactly the same. Bought from the driver's wallet earnings or by UPI; the fee is platform
subscription revenue, posted through the ledger."""

from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.conf import driver_day_pass_price
from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import DriverDayPass, DriverProfile


def _day(at: datetime | None) -> date:
    return timezone.localdate(at or timezone.now())


def price_for(driver: DriverProfile) -> Decimal:
    vehicle = driver.active_vehicle
    return driver_day_pass_price(vehicle.ride_type.code if vehicle else "MINI")


def active(driver: DriverProfile, at: datetime | None = None) -> bool:
    return DriverDayPass.objects.filter(driver=driver, day=_day(at)).exists()


def status(driver: DriverProfile, at: datetime | None = None) -> dict:
    from apps.rides.models import Trip, TripStatus

    day = _day(at)
    kept = Trip.objects.filter(
        driver=driver, status=TripStatus.COMPLETED, completed_at__date=day
    ).aggregate(total=Sum("commission_waived", default=Decimal(0)))["total"]
    return {
        "price": price_for(driver),
        "active_today": active(driver, at),
        "kept_today": kept,
        "day": day,
    }


@transaction.atomic
def buy(
    driver: DriverProfile, *, method: str, payer_reference: str = "", now=None
) -> DriverDayPass:
    from apps.payments import accounts
    from apps.payments.models import PaymentMethod, PaymentPurpose, PaymentStatus, TransactionKind
    from apps.payments.services import ensure_wallet, gateway_charge, post, wallet_balance

    now = now or timezone.now()
    price = price_for(driver)
    if active(driver, now):
        raise ConflictError("You already have today's day pass.")
    if method == PaymentMethod.WALLET:
        if wallet_balance(driver.user) < price:
            raise BusinessRuleViolation("Not enough earnings in your wallet.", field="method")
        source = ensure_wallet(driver.user)
    elif method == PaymentMethod.UPI:
        payment, _ = gateway_charge(
            user=driver.user,
            amount=price,
            method=method,
            purpose=PaymentPurpose.PASS,
            payer_reference=payer_reference,
        )
        if payment.status != PaymentStatus.SUCCEEDED:
            raise BusinessRuleViolation(f"Payment failed: {payment.failure_reason}")
        source = accounts.GATEWAY
    else:
        raise BusinessRuleViolation("Pay from your wallet or by UPI.", field="method")
    reference = next_reference("DPASS", year=now.year, width=6)
    try:
        with transaction.atomic():
            day_pass = DriverDayPass.objects.create(
                driver=driver,
                day=_day(now),
                price=price,
                payment_method=method,
                reference=reference,
            )
    except IntegrityError as exc:
        raise ConflictError("You already have today's day pass.") from exc
    post(
        TransactionKind.DRIVER_PASS,
        [(source, -price), (accounts.PLATFORM_SUBSCRIPTIONS, price)],
        description=f"Driver day pass {reference}",
        at=now,
    )
    notify(
        driver.user,
        "Day pass active: 0% commission today",
        f"You keep the whole fare on every trip until midnight. ₹{price} paid.",
        level=Level.SUCCESS,
        link="/drive/earnings",
    )
    return day_pass
