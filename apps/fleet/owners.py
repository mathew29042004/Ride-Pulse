"""Fleet owners (like Uber/Ola fleet partners): a business owns cars and employs drivers.

* Ops (fleet executives and up) sign owners up and attach drivers and vehicles to them.
* On every completed trip, the owner's share of the driver's trip earnings (``share_percent``;
  boosts and tips stay 100% with the driver) moves from the driver's wallet to the owner's.
* Owners have their own portal: drivers online now, trips and earnings, vehicle upkeep, and
  weekly payouts of their share.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.conf import _decimal
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.drivers.models import Availability, DriverProfile, Vehicle
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.payments.models import TransactionKind
from apps.payments.services import ensure_wallet, post, wallet_balance
from apps.rides.models import Trip, TripStatus

from .models import FleetMembership, FleetOwner

User = get_user_model()
CENT = Decimal("0.01")


@transaction.atomic
def create_owner(
    *,
    email: str,
    first_name: str,
    last_name: str,
    phone: str,
    company_name: str,
    city,
    gstin: str = "",
    share_percent: Decimal | None = None,
    account_manager=None,
    password: str | None = None,
) -> FleetOwner:
    if User.objects.filter(email__iexact=email).exists():
        raise ConflictError("Someone already uses that email.", field="email")
    share = share_percent if share_percent is not None else _decimal("FLEET_OWNER_SHARE_PERCENT")
    if not 0 <= share <= 50:
        raise BusinessRuleViolation("The owner's share must be 0-50%.", field="share_percent")
    user = User.objects.create_user(
        email,
        password,
        role=Role.FLEET_OWNER,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    return FleetOwner.objects.create(
        user=user,
        company_name=company_name,
        city=city,
        gstin=gstin.upper(),
        share_percent=share,
        account_manager=account_manager,
    )


def active_membership(driver: DriverProfile) -> FleetMembership | None:
    return (
        FleetMembership.objects.filter(driver=driver, left_at__isnull=True)
        .select_related("owner__user")
        .first()
    )


@transaction.atomic
def add_driver(owner: FleetOwner, driver: DriverProfile, *, now: datetime | None = None):
    now = now or timezone.now()
    if driver.city_id != owner.city_id:
        raise BusinessRuleViolation("The driver works in another city.", field="driver")
    current = active_membership(driver)
    if current and current.owner_id == owner.pk:
        return current
    if current:
        raise ConflictError(f"{driver.name} already drives for {current.owner.company_name}.")
    membership = FleetMembership.objects.create(owner=owner, driver=driver, joined_at=now)
    Vehicle.objects.filter(driver=driver, is_active=True, owner__isnull=True).update(owner=owner)
    notify(
        driver.user,
        f"You now drive for {owner.company_name}",
        f"{owner.share_percent:g}% of your trip earnings go to the fleet owner. Tips and boosts "
        "stay 100% yours.",
        level=Level.INFO,
    )
    return membership


@transaction.atomic
def remove_driver(owner: FleetOwner, driver: DriverProfile, *, now: datetime | None = None):
    now = now or timezone.now()
    updated = FleetMembership.objects.filter(
        owner=owner, driver=driver, left_at__isnull=True
    ).update(left_at=now)
    if not updated:
        raise BusinessRuleViolation("That driver isn't in this fleet.")
    notify(driver.user, f"You no longer drive for {owner.company_name}", level=Level.INFO)


def owner_share(trip: Trip, percent: Decimal) -> Decimal:
    """The owner's cut of the trip earnings, never of boosts (or tips, kept separately)."""
    base = max(Decimal(0), (trip.driver_earning or 0) - (trip.boost_amount or 0))
    return (base * percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)


def on_trip_completed(trip: Trip) -> Decimal:
    """Called after a trip is completed and settled: pays the fleet owner's share."""
    membership = active_membership(trip.driver)
    if membership is None or not membership.owner.is_active:
        return Decimal(0)
    share = owner_share(trip, membership.owner.share_percent)
    if share <= 0:
        return Decimal(0)
    post(
        TransactionKind.FLEET_SHARE,
        [(ensure_wallet(trip.driver.user), -share), (ensure_wallet(membership.owner.user), share)],
        trip=trip,
        description=f"{membership.owner.company_name}: {membership.owner.share_percent:g}% of "
        f"{trip.trip_number}",
        at=trip.completed_at,
    )
    return share


# --- The owner's portal -----------------------------------------------------------------------


def owner_for(user) -> FleetOwner:
    owner = getattr(user, "fleet_owner", None)
    if owner is None:
        raise ActionNotPermitted("This page is for fleet owners.")
    return owner


def dashboard(owner: FleetOwner, *, now: datetime | None = None) -> dict:
    from .maintenance import costs, history, vehicle_health, with_health_data

    now = now or timezone.now()
    today = timezone.make_aware(datetime.combine(timezone.localdate(now), datetime.min.time()))
    week = today - timedelta(days=timezone.localdate(now).weekday())
    member_ids = list(
        FleetMembership.objects.filter(owner=owner, left_at__isnull=True).values_list(
            "driver_id", flat=True
        )
    )
    drivers = DriverProfile.objects.filter(pk__in=member_ids).select_related("user")
    trips = Trip.objects.filter(driver_id__in=member_ids, status=TripStatus.COMPLETED)
    per_driver = {
        row["driver_id"]: row
        for row in trips.filter(completed_at__gte=week)
        .values("driver_id")
        .annotate(
            week_trips=Count("pk"),
            today_trips=Count("pk", filter=Q(completed_at__gte=today)),
            earnings=Sum("driver_earning"),
        )
    }
    # The owner's real share comes from the ledger (FLEET_SHARE postings into their wallet).
    from apps.payments.models import LedgerEntry, TransactionKind

    shares = dict(
        LedgerEntry.objects.filter(
            wallet__user=owner.user,
            transaction__kind=TransactionKind.FLEET_SHARE,
            transaction__created_at__gte=week,
        )
        .values_list("transaction__trip__driver_id")
        .annotate(total=Sum("amount"))
        .values_list("transaction__trip__driver_id", "total")
    )
    share = owner.share_percent
    rows = []
    for d in drivers:
        stats = per_driver.get(d.pk, {})
        rows.append(
            {
                "id": d.pk,
                "name": d.name,
                "phone": d.user.phone,
                "availability": d.availability,
                "rating": str(d.rating),
                "today_trips": stats.get("today_trips", 0),
                "week_trips": stats.get("week_trips", 0),
                "week_earnings": str(stats.get("earnings") or 0),
                "week_share": str(shares.get(d.pk) or Decimal("0.00")),
            }
        )
    rows.sort(key=lambda r: (-r["week_trips"], r["name"]))
    vehicles = with_health_data(
        Vehicle.objects.filter(owner=owner, is_active=True).select_related(
            "driver__user", "ride_type"
        )
    )
    from apps.payments.models import Payout

    return {
        "company": owner.company_name,
        "city": owner.city.name,
        "share_percent": str(share),
        "account_manager": owner.account_manager.user.get_full_name()
        if owner.account_manager
        else None,
        "drivers": rows,
        "online": sum(1 for d in drivers if d.availability != Availability.OFFLINE),
        "today_trips": sum(r["today_trips"] for r in rows),
        "week_trips": sum(r["week_trips"] for r in rows),
        "week_share": str(sum(Decimal(r["week_share"]) for r in rows)),
        "balance": str(wallet_balance(owner.user)),
        "vehicles": [
            {**vehicle_health(v, now=now), "costs": costs(v), "history": history(v, limit=5)}
            for v in vehicles
        ],
        "payouts": [
            {
                "number": p.payout_number,
                "amount": str(p.amount),
                "status": p.get_status_display(),
                "period": f"{p.period_start:%d %b} – {p.period_end:%d %b}",
            }
            for p in Payout.objects.filter(fleet_owner=owner)[:8]
        ],
    }
