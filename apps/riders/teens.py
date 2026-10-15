"""Teen accounts (like Uber for Teens): a parent links their 13-17-year-old.

* The parent invites the teen's existing rider account by phone; the teen accepts and confirms
  their birth year. A family profile ("Teen: <name>") is created behind the scenes with the
  parent paying and a monthly limit the parent sets.
* Every teen booking is billed to that profile (wallet only, never cash), refused during the
  curfew (default 10 pm - 6 am), cars and autos only (no bike taxis), and matched only with
  experienced, top-rated drivers (rating 4.8+, 100+ trips).
* The parent is told when a driver is assigned (with the live tracking link), when the ride
  starts and when the teen arrives. The ride PIN is always required.
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.core.validators import normalize_indian_mobile
from apps.notifications.models import Level
from apps.notifications.services import notify

from . import profiles
from .models import MemberStatus, ProfileKind, RiderProfile, TeenLink, TeenStatus

MIN_AGE, MAX_AGE = 13, 17
TEEN_MIN_RATING = Decimal("4.80")
TEEN_MIN_TRIPS = 100
TEEN_RIDE_TYPES_EXCLUDED = {"BIKE", "PARCEL"}


def active_link(rider: RiderProfile) -> TeenLink | None:
    return (
        TeenLink.objects.filter(teen=rider, status=TeenStatus.ACTIVE)
        .select_related("guardian__user", "profile")
        .first()
    )


@transaction.atomic
def invite(guardian: RiderProfile, *, phone: str, monthly_limit: Decimal | None = None) -> TeenLink:
    try:
        phone = normalize_indian_mobile(phone)
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="phone") from exc
    teen = RiderProfile.objects.filter(user__phone=phone).select_related("user").first()
    if teen is None:
        raise BusinessRuleViolation(
            "No Ride Pulse rider has that number. Ask your teen to sign up with it first.",
            field="phone",
        )
    if teen.pk == guardian.pk:
        raise BusinessRuleViolation("That's your own number.", field="phone")
    if TeenLink.objects.filter(
        teen=teen, status__in=[TeenStatus.INVITED, TeenStatus.ACTIVE]
    ).exists():
        raise ConflictError("That account is already linked to a parent.")
    if TeenLink.objects.filter(teen=guardian, status=TeenStatus.ACTIVE).exists():
        raise ActionNotPermitted("Teen accounts can't add teens.")
    profile = profiles.create_profile(
        guardian, kind=ProfileKind.FAMILY, name=f"Teen: {teen.user.first_name}"
    )
    link = TeenLink.objects.create(guardian=guardian, teen=teen, birth_year=0, profile=profile)
    member = profiles.invite(profile, user=guardian.user, phone=phone)
    if monthly_limit is not None:
        profiles.update_member(member, user=guardian.user, monthly_limit=monthly_limit)
    notify(
        teen.user,
        f"{guardian.user.first_name} wants to set up a teen account for you",
        "Your rides will be paid by them and shared with them live. Open Account to accept.",
        level=Level.INFO,
        link="/ride/account",
    )
    return link


@transaction.atomic
def accept(link: TeenLink, *, user, birth_year: int, now: datetime | None = None) -> TeenLink:
    now = now or timezone.now()
    if link.teen.user_id != user.pk:
        raise ActionNotPermitted("This invitation is for someone else.")
    if link.status != TeenStatus.INVITED:
        raise ConflictError("This invitation was already answered.")
    age = timezone.localdate(now).year - birth_year
    if not MIN_AGE <= age <= MAX_AGE + 1:  # born late in the year: may still be 17
        raise BusinessRuleViolation("Teen accounts are for ages 13 to 17.", field="birth_year")
    link.birth_year, link.status = birth_year, TeenStatus.ACTIVE
    link.save(update_fields=["birth_year", "status"])
    member = link.profile.members.get(rider=link.teen)
    profiles.respond(member, user=user, accept=True)
    notify(
        link.guardian.user,
        f"{link.teen.user.first_name}'s teen account is ready",
        level=Level.SUCCESS,
    )
    return link


def decline_or_end(link: TeenLink, *, user, now: datetime | None = None) -> TeenLink:
    if user.pk not in (link.guardian.user_id, link.teen.user_id):
        raise ActionNotPermitted("Only the parent or the teen can do that.")
    link.status, link.ended_at = TeenStatus.ENDED, now or timezone.now()
    link.save(update_fields=["status", "ended_at"])
    if link.profile_id:
        member = link.profile.members.filter(rider=link.teen).first()
        if member and member.status in (MemberStatus.ACTIVE, MemberStatus.INVITED):
            member.status = MemberStatus.REMOVED
            member.save(update_fields=["status"])
        profiles.deactivate(link.profile, user=link.guardian.user)
    return link


def set_curfew(link: TeenLink, *, user, start: int, end: int) -> TeenLink:
    if link.guardian.user_id != user.pk:
        raise ActionNotPermitted("Only the parent can change the curfew.")
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise BusinessRuleViolation("Hours are 0-23.", field="curfew")
    link.curfew_start, link.curfew_end = start, end
    link.save(update_fields=["curfew_start", "curfew_end"])
    return link


def in_curfew(link: TeenLink, at: datetime) -> bool:
    hour = timezone.localtime(at).hour
    start, end = link.curfew_start, link.curfew_end
    if start == end:
        return False
    return start <= hour or hour < end if start > end else start <= hour < end


def booking_rules(rider: RiderProfile, *, ride_type, payment_profile, now: datetime):
    """Applied to every booking by a teen. Returns the profile the ride must be billed to."""
    link = active_link(rider)
    if link is None:
        return payment_profile, False
    if in_curfew(link, now):
        raise BusinessRuleViolation(
            f"Teen rides aren't available between {link.curfew_start}:00 and "
            f"{link.curfew_end}:00. Ask {link.guardian.user.first_name} to book for you.",
        )
    if ride_type.code in TEEN_RIDE_TYPES_EXCLUDED:
        raise BusinessRuleViolation("Teen accounts can book cars and autos.", field="ride_type")
    if payment_profile is not None and payment_profile.pk != link.profile_id:
        raise BusinessRuleViolation(
            "Teen rides are paid by your parent's account.", field="payment_profile"
        )
    return link.profile, True


def tell_guardian(trip, event: str) -> None:
    """Keep the parent in the loop: assigned (with the live link), started, arrived."""
    link = active_link(trip.rider)
    if link is None:
        return
    teen = trip.rider.user.first_name
    if event == "assigned":
        from apps.rides.services import share_trip

        token = share_trip(trip, user=trip.rider.user)
        title = f"{teen} booked a ride: {trip.driver.name} is on the way"
        body = f"{trip.vehicle} · follow live at /track/{token}"
        link_url = f"/track/{token}"
    elif event == "started":
        title, body, link_url = f"{teen}'s ride has started", f"To {trip.dropoff_address}", ""
    else:
        title, body, link_url = f"{teen} has arrived", f"At {trip.dropoff_address}", ""
    notify(link.guardian.user, title, body, level=Level.INFO, link=link_url)


def guardian_view(guardian: RiderProfile) -> list[dict]:
    from apps.riders.profiles import spent_this_month
    from apps.rides.models import ACTIVE_STATUSES, Trip

    rows = []
    for link in (
        TeenLink.objects.filter(guardian=guardian)
        .exclude(status=TeenStatus.ENDED)
        .select_related("teen__user", "profile")
    ):
        member = link.profile.members.filter(rider=link.teen).first() if link.profile_id else None
        active = Trip.objects.filter(rider=link.teen, status__in=ACTIVE_STATUSES).first()
        rows.append(
            {
                "id": link.pk,
                "name": link.teen.user.get_full_name(),
                "status": link.status,
                "curfew": [link.curfew_start, link.curfew_end],
                "monthly_limit": str(member.monthly_limit)
                if member and member.monthly_limit
                else None,
                "spent_this_month": str(
                    spent_this_month(link.profile, link.teen, timezone.now()) if member else 0
                ),
                "active_trip": {
                    "status": active.get_status_display(),
                    "track": f"/track/{active.share_token}" if active.share_token else None,
                }
                if active
                else None,
            }
        )
    return rows
