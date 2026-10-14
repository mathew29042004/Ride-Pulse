"""Family and business profiles: one payer for several riders.

* **Family.** The family head creates a profile and invites family members by phone. Members
  can book rides paid from the head's wallet, optionally within a monthly limit each. The head
  is notified of every ride.
* **Business.** A company's travel desk account does the same for employees, with a trip
  purpose on every ride, a monthly statement (and CSV), the company GSTIN on invoices, and an
  optional credit limit so rides can be billed monthly instead of prepaid.

The owner can always book on their own profile. Payment goes through the normal ledger: the
fare comes out of the owner's wallet instead of the rider's (see payments.settle_trip).
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.core.validators import normalize_indian_mobile
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import MemberStatus, PaymentProfile, ProfileKind, ProfileMember, RiderProfile

MAX_PROFILES_PER_OWNER = 3
MAX_MEMBERS = 20


def create_profile(owner: RiderProfile, *, kind: str, name: str, gstin: str = "") -> PaymentProfile:
    if kind not in ProfileKind.values:
        raise BusinessRuleViolation("Choose family or business.", field="kind")
    name = " ".join(name.split())[:80]
    if len(name) < 2:
        raise BusinessRuleViolation("Give the profile a name.", field="name")
    if owner.owned_profiles.filter(is_active=True).count() >= MAX_PROFILES_PER_OWNER:
        raise BusinessRuleViolation(f"You can own up to {MAX_PROFILES_PER_OWNER} profiles.")
    gstin = gstin.strip().upper()
    if gstin and len(gstin) != 15:
        raise BusinessRuleViolation("A GSTIN has 15 characters.", field="gstin")
    return PaymentProfile.objects.create(
        owner=owner, kind=kind, name=name, gstin=gstin if kind == ProfileKind.BUSINESS else ""
    )


def _require_owner(profile: PaymentProfile, user) -> None:
    if profile.owner.user_id != user.pk:
        raise ActionNotPermitted("Only the profile's owner can do this.")


def invite(profile: PaymentProfile, *, user, phone: str) -> ProfileMember:
    _require_owner(profile, user)
    try:
        phone = normalize_indian_mobile(phone)
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="phone") from exc
    rider = RiderProfile.objects.filter(user__phone=phone).select_related("user").first()
    if rider is None:
        raise BusinessRuleViolation(
            "No Ride Pulse rider has that number. Ask them to sign up first.", field="phone"
        )
    if rider.pk == profile.owner_id:
        raise BusinessRuleViolation("You're the owner already.", field="phone")
    if profile.members.exclude(status=MemberStatus.REMOVED).count() >= MAX_MEMBERS:
        raise BusinessRuleViolation(f"A profile can have up to {MAX_MEMBERS} members.")
    member, created = ProfileMember.objects.get_or_create(profile=profile, rider=rider)
    if not created:
        if member.status in (MemberStatus.ACTIVE, MemberStatus.INVITED):
            raise ConflictError("They're already a member or invited.")
        member.status = MemberStatus.INVITED
        member.save(update_fields=["status"])
    notify(
        rider.user,
        f"{profile.owner.name} invited you to {profile.name}",
        f"Rides you book on this {profile.get_kind_display().lower()} profile are paid by them.",
        level=Level.INFO,
        link="/ride/account",
    )
    return member


def respond(member: ProfileMember, *, user, accept: bool) -> ProfileMember:
    if member.rider.user_id != user.pk:
        raise ActionNotPermitted("This invitation is for someone else.")
    if member.status != MemberStatus.INVITED:
        raise ConflictError("This invitation was already answered.")
    member.status = MemberStatus.ACTIVE if accept else MemberStatus.DECLINED
    member.joined_at = timezone.now() if accept else None
    member.save(update_fields=["status", "joined_at"])
    if accept:
        notify(
            member.profile.owner.user,
            f"{member.rider.name} joined {member.profile.name}",
            "They can now book rides on this profile.",
            level=Level.SUCCESS,
            link="/ride/account",
        )
    return member


def update_member(
    member: ProfileMember, *, user, monthly_limit: Decimal | None = None, remove: bool = False
) -> ProfileMember:
    _require_owner(member.profile, user)
    if remove:
        member.status = MemberStatus.REMOVED
        member.save(update_fields=["status"])
        return member
    if monthly_limit is not None and monthly_limit < 0:
        raise BusinessRuleViolation("The limit can't be negative.", field="monthly_limit")
    member.monthly_limit = monthly_limit
    member.save(update_fields=["monthly_limit"])
    return member


def usable_profiles(rider: RiderProfile):
    """Profiles this rider can book on: their own, and those they're an active member of."""
    return (
        PaymentProfile.objects.filter(is_active=True)
        .filter(Q(owner=rider) | Q(members__rider=rider, members__status=MemberStatus.ACTIVE))
        .distinct()
    )


def _month_start(at: datetime) -> datetime:
    local = timezone.localtime(at)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(profile: PaymentProfile, rider: RiderProfile, at: datetime) -> Decimal:
    from apps.rides.models import TripStatus

    trips = profile.trips.filter(rider=rider, requested_at__gte=_month_start(at))
    done = trips.filter(status=TripStatus.COMPLETED).aggregate(
        s=Sum("fare_total", default=Decimal(0))
    )["s"]
    open_ = trips.exclude(
        status__in=[TripStatus.COMPLETED, TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND]
    ).aggregate(s=Sum("estimated_fare", default=Decimal(0)))["s"]
    return done + open_


def check_booking(
    profile: PaymentProfile, rider: RiderProfile, *, fare: Decimal, purpose: str, at: datetime
) -> str:
    """Raise if this rider can't book this fare on the profile; return the cleaned purpose."""
    from apps.payments.services import wallet_balance

    if not profile.is_active:
        raise BusinessRuleViolation("This profile is no longer active.", field="payment_profile")
    if profile.owner_id != rider.pk:
        member = profile.members.filter(rider=rider, status=MemberStatus.ACTIVE).first()
        if member is None:
            raise ActionNotPermitted("You're not a member of this profile.")
        if member.monthly_limit is not None:
            left = member.monthly_limit - spent_this_month(profile, rider, at)
            if fare > left:
                raise BusinessRuleViolation(
                    f"This ride is over your monthly limit on {profile.name} "
                    f"(₹{max(left, Decimal(0)):,.2f} left).",
                    field="payment_profile",
                )
    purpose = " ".join(purpose.split())[:120]
    if profile.kind == ProfileKind.BUSINESS and len(purpose) < 3:
        raise BusinessRuleViolation("Add the purpose of this business trip.", field="trip_purpose")
    balance = wallet_balance(profile.owner.user)
    if balance - fare < -profile.credit_limit:
        raise BusinessRuleViolation(
            f"{profile.name}'s balance doesn't cover this ride. "
            f"Ask {profile.owner.name} to top up.",
            field="payment_profile",
        )
    return purpose


def statement(profile: PaymentProfile, *, user, month: str | None = None) -> dict:
    """The owner's monthly statement: every ride on the profile, by member."""
    from apps.rides.models import TripStatus

    _require_owner(profile, user)
    now = timezone.now()
    if month:
        try:
            start = timezone.make_aware(datetime.strptime(month, "%Y-%m"))
        except ValueError as exc:
            raise BusinessRuleViolation("Use the YYYY-MM format.", field="month") from exc
    else:
        start = _month_start(now)
    end = (start.replace(day=28) + timezone.timedelta(days=4)).replace(day=1)
    trips = (
        profile.trips.filter(
            status=TripStatus.COMPLETED, completed_at__gte=start, completed_at__lt=end
        )
        .select_related("rider__user", "ride_type")
        .order_by("completed_at")
    )
    rows = [
        {
            "trip_number": t.trip_number,
            "date": timezone.localtime(t.completed_at).strftime("%Y-%m-%d %H:%M"),
            "rider": t.rider.name,
            "ride_type": t.ride_type.name,
            "from": t.pickup_address,
            "to": t.dropoff_address,
            "purpose": t.trip_purpose,
            "fare": t.fare_total,
            "gst": t.gst_amount,
        }
        for t in trips
    ]
    return {
        "profile": profile.name,
        "kind": profile.kind,
        "gstin": profile.gstin,
        "month": start.strftime("%Y-%m"),
        "rides": len(rows),
        "total": sum((r["fare"] for r in rows), Decimal(0)),
        "gst": sum((r["gst"] for r in rows), Decimal(0)),
        "trips": rows,
    }


def charge_notice(trip) -> None:
    """Tell the owner when someone else's ride is charged to their profile."""
    profile = trip.payment_profile
    if profile is None or profile.owner_id == trip.rider_id:
        return
    notify(
        profile.owner.user,
        f"{trip.rider.name}'s ride: ₹{trip.fare_total} on {profile.name}",
        f"{trip.pickup_address} → {trip.dropoff_address}"
        + (f" · {trip.trip_purpose}" if trip.trip_purpose else ""),
        level=Level.INFO,
        link="/ride/account",
    )


@transaction.atomic
def deactivate(profile: PaymentProfile, *, user) -> PaymentProfile:
    _require_owner(profile, user)
    profile.is_active = False
    profile.save(update_fields=["is_active"])
    return profile
