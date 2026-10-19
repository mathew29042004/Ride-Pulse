"""The specialist roles' powers.

* **Finance manager** (``refund.approve``): refunds above ``REFUND_LIMIT`` that support issue
  don't go out straight away; they wait here until finance approves (the refund is then paid to
  the rider's wallet) or declines (the rider is told why).
* **Safety officer** (``safety.ban``): ban a driver or rider for good. Their account is
  suspended or blocked, and their phone (and a driver's licence) go on the ban list, so they
  can't sign up again under a new email. A ban can be lifted, with a reason.
* **Dispatch controller** (``dispatch.assign``): hand a waiting trip to a chosen online driver,
  bypassing the automatic ranking (e.g. the only driver with a wheelchair ramp nearby).
* **Compliance officer** (``legal.hold``): freeze a person's data during a police or court
  case. Their data-erasure request can't complete while the hold is on.
* **HR manager** (``people.manage``): move an employee to another manager or city, or change
  their role (never to or from the top roles), with the reason recorded.

Every action is written to the audit log.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition

REFUND_LIMIT = Decimal(2000)  # ₹; larger refunds need finance approval


class RefundApproval(models.Model):
    PENDING, APPROVED, DECLINED = "PENDING", "APPROVED", "DECLINED"
    STATUSES = [(PENDING, "Waiting for finance"), (APPROVED, "Approved"), (DECLINED, "Declined")]

    trip = models.ForeignKey("rides.Trip", on_delete=models.CASCADE, related_name="+")
    ticket = models.ForeignKey(
        "support.SupportTicket", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=300)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    requested_at = models.DateTimeField()
    status = models.CharField(max_length=8, choices=STATUSES, default=PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"₹{self.amount} refund for {self.trip_id}"


class Ban(models.Model):
    """A banned phone number or driving licence."""

    kind = models.CharField(max_length=8, choices=[("PHONE", "Phone"), ("LICENCE", "Licence")])
    value = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=300)
    banned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    banned_at = models.DateTimeField()
    lifted_at = models.DateTimeField(null=True, blank=True)
    lift_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-banned_at"]

    def __str__(self) -> str:
        return f"Banned {self.kind.lower()} {self.value}"


class LegalHold(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    case_reference = models.CharField(max_length=80)
    reason = models.CharField(max_length=300)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    placed_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-placed_at"]

    def __str__(self) -> str:
        return f"Legal hold {self.case_reference}"


def _audit(instance, message: str, actor) -> None:
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    log_event(AuditAction.ACTION, instance, message=message[:255], actor=actor)


# --- Finance: refund approvals -------------------------------------------------------------------


def needs_approval(amount, actor) -> bool:
    return Decimal(str(amount)) > REFUND_LIMIT and not actor.has_capability("refund.approve")


def request_refund(*, trip, amount, reason: str, actor, ticket=None, now=None) -> RefundApproval:
    from apps.accounts.models import User
    from apps.notifications.services import notify

    now = now or timezone.now()
    r = RefundApproval.objects.create(
        trip=trip,
        ticket=ticket,
        amount=Decimal(str(amount)),
        reason=reason[:300],
        requested_by=actor,
        requested_at=now,
    )
    for u in User.objects.filter(role="FINANCE_MANAGER", is_active=True)[:10]:
        notify(
            u,
            f"Refund of ₹{r.amount:,.0f} needs your approval",
            f"{trip.trip_number}: {reason[:150]}",
            link="/ops/powers",
        )
    _audit(r, f"Refund ₹{r.amount} sent to finance for approval", actor)
    return r


@transaction.atomic
def decide_refund(r: RefundApproval, *, actor, approve: bool, note: str = "", now=None):
    from apps.notifications.services import notify
    from apps.payments.services import refund_to_wallet

    if not actor.has_capability("refund.approve"):
        raise ActionNotPermitted("Only finance can approve large refunds.")
    r = RefundApproval.objects.select_for_update().get(pk=r.pk)
    if r.status != RefundApproval.PENDING:
        raise InvalidStateTransition("This refund has already been decided.")
    if not approve and len(note.strip()) < 5:
        raise BusinessRuleViolation("Say why it's declined; the rider will be told.", field="note")
    if approve:
        refund_to_wallet(r.trip, r.amount, reason=r.reason, actor=actor)
    else:
        notify(
            r.trip.rider.user,
            f"About your refund for {r.trip.trip_number}",
            f"We couldn't approve the ₹{r.amount:,.0f} refund: {note.strip()}",
        )
    r.status = RefundApproval.APPROVED if approve else RefundApproval.DECLINED
    r.decided_by, r.decided_at, r.note = actor, now or timezone.now(), note.strip()[:300]
    r.save()
    notify(r.requested_by, f"Finance {r.get_status_display().lower()} the refund", r.note or "")
    _audit(r, f"Refund {r.get_status_display().lower()}", actor)
    from apps.reliability.briefing import system_update

    system_update(
        f"Large refund {r.get_status_display().lower()}: ₹{r.amount:,.0f}",
        f"{r.trip.trip_number}: {r.reason} (by {actor.get_full_name()})",
        source="Finance",
    )
    return r


# --- Safety: bans ------------------------------------------------------------------------------


def banned(*, phone: str = "", licence: str = "") -> bool:
    q = models.Q(pk__in=[])
    if phone:
        q |= models.Q(kind="PHONE", value=phone[-10:])
    if licence:
        q |= models.Q(kind="LICENCE", value=licence.upper().replace(" ", ""))
    return Ban.objects.filter(q, lifted_at__isnull=True).exists()


@transaction.atomic
def ban(user, *, actor, reason: str, now=None) -> list[Ban]:
    from apps.drivers import services as drivers
    from apps.riders import services as riders

    now = now or timezone.now()
    if len(reason.strip()) < 10:
        raise BusinessRuleViolation("Describe what happened (10+ characters).", field="reason")
    if user.is_staff_member and not user.is_end_user:
        raise BusinessRuleViolation("Staff are dismissed by HR, not banned here.")
    driver = getattr(user, "driver_profile", None)
    rider = getattr(user, "rider_profile", None)
    if driver and driver.onboarding_status != "SUSPENDED":
        drivers.suspend_driver(driver, reason=f"Banned: {reason}", actor=actor)
    if rider and not rider.is_blocked:
        riders.set_blocked(rider, True, reason=f"Banned: {reason}", actor=actor)
    made = []
    if user.phone:
        made.append(("PHONE", user.phone[-10:]))
    if driver and driver.license_number:
        made.append(("LICENCE", driver.license_number.upper().replace(" ", "")))
    rows = [
        Ban.objects.create(
            kind=k, value=v, user=user, reason=reason.strip()[:300], banned_by=actor, banned_at=now
        )
        for k, v in made
    ]
    _audit(user, f"Banned for good: {reason}", actor)
    from apps.reliability.briefing import system_update

    system_update(
        f"{user.get_full_name()} banned for good",
        f"{reason.strip()} (by {actor.get_full_name()})",
        source="Safety desk",
    )
    return rows


def lift_ban(user, *, actor, reason: str, now=None) -> int:
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation("Give a reason.", field="reason")
    n = Ban.objects.filter(user=user, lifted_at__isnull=True).update(
        lifted_at=now or timezone.now(), lift_reason=reason.strip()[:300]
    )
    _audit(user, f"Ban lifted: {reason}", actor)
    return n


# --- Dispatch: hand a trip to a chosen driver ---------------------------------------------------


@transaction.atomic
def assign_to(trip, driver, *, actor, now=None):
    """Offer this waiting trip to this driver right now (any other open offers are withdrawn)."""
    from apps.drivers.models import Availability
    from apps.geo.distance import haversine_km
    from apps.rides import dispatch
    from apps.rides.models import Trip, TripStatus

    now = now or timezone.now()
    trip = Trip.objects.select_for_update().get(pk=trip.pk)
    if trip.status != TripStatus.REQUESTED:
        raise InvalidStateTransition("Only a trip still looking for a driver can be assigned.")
    if driver.availability != Availability.ONLINE or driver.current_lat is None:
        raise BusinessRuleViolation("That driver isn't online and free.", field="driver")
    km = haversine_km(driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng)
    if km > 15:
        raise BusinessRuleViolation(f"That driver is {km:.0f} km away.", field="driver")
    dispatch.withdraw_trip_offers(trip, now=now)
    offer = dispatch._create_offer(
        trip,
        dispatch.Candidate(driver=driver, distance_km=km, eta_minutes=km * 3, score=1.0),
        now=now,
        mode="MANUAL",
    )
    if offer is None:
        raise BusinessRuleViolation("That driver has another offer open; try again shortly.")
    _audit(trip, f"Manually offered to {driver.name} by dispatch", actor)
    return offer


# --- Compliance: legal holds ---------------------------------------------------------------------


def on_hold(user) -> LegalHold | None:
    return LegalHold.objects.filter(user=user, released_at__isnull=True).first()


def place_hold(user, *, actor, case_reference: str, reason: str, now=None) -> LegalHold:
    if not case_reference.strip() or len(reason.strip()) < 10:
        raise BusinessRuleViolation("Give the case reference and the reason.")
    if on_hold(user):
        raise BusinessRuleViolation("There's already a hold on this person.")
    hold = LegalHold.objects.create(
        user=user,
        case_reference=case_reference.strip()[:80],
        reason=reason.strip()[:300],
        placed_by=actor,
        placed_at=now or timezone.now(),
    )
    _audit(user, f"Legal hold {hold.case_reference}: {hold.reason}", actor)
    from apps.reliability.briefing import system_update

    system_update(
        f"Legal hold placed ({hold.case_reference})",
        f"{user.get_full_name()}: {hold.reason} (by {actor.get_full_name()})",
        source="Legal & compliance",
    )
    return hold


def release_hold(hold: LegalHold, *, actor, now=None) -> LegalHold:
    hold.released_at = now or timezone.now()
    hold.save(update_fields=["released_at"])
    _audit(hold.user, f"Legal hold {hold.case_reference} released", actor)
    return hold


# --- HR: transfers and role changes ---------------------------------------------------------------

LOCKED_ROLES = {"COMMANDER", "CHIEF_OF_STAFF", "ADMIN", "DRIVER", "RIDER", "FLEET_OWNER"}


@transaction.atomic
def transfer(employee, *, actor, manager=None, city=None, role: str = "", reason: str, now=None):
    from apps.accounts.models import Role, StaffProfile
    from apps.notifications.services import notify

    if len(reason.strip()) < 5:
        raise BusinessRuleViolation("Give a reason.", field="reason")
    profile = StaffProfile.objects.select_for_update().get(user=employee)
    changes = []
    if role:
        if role not in Role.values or role in LOCKED_ROLES or employee.role in LOCKED_ROLES:
            raise BusinessRuleViolation("HR can't give or take away that role.", field="role")
        if role != employee.role:
            changes.append(f"role {employee.get_role_display()} → {Role(role).label}")
            employee.role = role
            employee.save(update_fields=["role"])
    if manager is not None and manager.pk != profile.reports_to_id:
        if manager.user_id == employee.pk:
            raise BusinessRuleViolation("Nobody reports to themselves.", field="manager")
        node = manager
        for _ in range(20):  # no loops in the org chart
            if node is None:
                break
            if node.user_id == employee.pk:
                raise BusinessRuleViolation("That would make a loop in the org chart.")
            node = node.reports_to
        changes.append(f"manager → {manager.user.get_full_name()}")
        profile.reports_to = manager
    if city is not None and city.pk != profile.city_id:
        changes.append(f"city → {city.name}")
        profile.city, profile.state = city, city.state
    if not changes:
        raise BusinessRuleViolation("Nothing to change.")
    profile.save()
    message = f"{'; '.join(changes)} ({reason.strip()})"
    _audit(employee, f"HR: {message}", actor)
    notify(employee, "Your position has changed", message, link="/ops/team")
    from apps.chat.services import sync_channels

    sync_channels()
    return profile


def overview(user) -> dict:
    """What each specialist sees on Ops → Powers (only the parts their role allows)."""
    out: dict = {}
    if user.has_capability("refund.approve"):
        out["refunds"] = [
            {
                "id": r.pk,
                "trip": r.trip.trip_number,
                "amount": r.amount,
                "reason": r.reason,
                "by": r.requested_by.get_full_name(),
                "at": r.requested_at.isoformat(),
                "status": r.status,
                "status_label": r.get_status_display(),
                "note": r.note,
            }
            for r in RefundApproval.objects.select_related("trip", "requested_by")[:30]
        ]
    if user.has_capability("safety.ban"):
        out["bans"] = [
            {
                "id": b.pk,
                "user_id": b.user_id,
                "who": b.user.get_full_name() if b.user else "",
                "kind": b.kind,
                "value": "•" * max(0, len(b.value) - 4) + b.value[-4:],
                "reason": b.reason,
                "at": b.banned_at.isoformat(),
                "lifted": b.lifted_at is not None,
            }
            for b in Ban.objects.select_related("user")[:30]
        ]
    if user.has_capability("legal.hold"):
        out["holds"] = [
            {
                "id": h.pk,
                "who": h.user.get_full_name(),
                "case": h.case_reference,
                "reason": h.reason,
                "at": h.placed_at.isoformat(),
                "released": h.released_at is not None,
            }
            for h in LegalHold.objects.select_related("user")[:30]
        ]
    if user.has_capability("dispatch.assign"):
        from apps.rides.models import Trip, TripStatus

        waiting = Trip.objects.filter(
            status=TripStatus.REQUESTED, requested_at__gte=timezone.now() - timedelta(minutes=30)
        ).select_related("city", "ride_type")[:20]
        out["waiting"] = [
            {
                "id": t.pk,
                "trip": t.trip_number,
                "city": t.city.name,
                "ride_type": t.ride_type.name,
                "pickup": t.pickup_address,
                "waiting_min": int((timezone.now() - t.requested_at).total_seconds() // 60),
            }
            for t in waiting
        ]
    if user.has_capability("people.manage"):
        from apps.accounts.models import Role

        out["roles"] = [
            {"value": v, "label": label} for v, label in Role.choices if v not in LOCKED_ROLES
        ]
    return out


def nearby_drivers(trip) -> list[dict]:
    from apps.drivers.models import Availability, DriverProfile
    from apps.geo.distance import haversine_km

    rows = []
    for d in DriverProfile.objects.filter(
        availability=Availability.ONLINE, city=trip.city, current_lat__isnull=False
    ).select_related("user")[:300]:
        km = haversine_km(d.current_lat, d.current_lng, trip.pickup_lat, trip.pickup_lng)
        if km <= 15:
            rows.append({"id": d.pk, "name": d.name, "km": round(km, 1), "rating": d.rating})
    return sorted(rows, key=lambda r: r["km"])[:10]


def seed_demo(*, log=print) -> dict:
    """A few large refunds waiting for finance (on real long-distance trips)."""
    from apps.accounts.models import User
    from apps.rides.models import Trip, TripStatus

    if RefundApproval.objects.exists():
        return {"refund_approvals": 0}
    agent = User.objects.filter(role="SUPPORT_LEAD", is_active=True).first()
    if agent is None:
        return {"refund_approvals": 0}
    made = 0
    for trip in Trip.objects.filter(
        status=TripStatus.COMPLETED, fare_total__gt=REFUND_LIMIT + 500
    ).order_by("-completed_at")[:3]:
        amount = (trip.fare_total * Decimal("0.6")).quantize(Decimal(1))
        if amount <= REFUND_LIMIT:
            continue
        request_refund(
            trip=trip,
            amount=amount,
            reason=f"{trip.trip_number}: AC not working for the whole intercity trip",
            actor=agent,
        )
        made += 1
    log(f"  refunds waiting for finance: {made}")
    return {"refund_approvals": made}


UNDO_WINDOW = timedelta(minutes=10)


@transaction.atomic
def undo_ban(user, *, actor, now=None) -> int:
    """Take back a ban made in the last 10 minutes: the bans are lifted and the driver
    reinstated or the rider unblocked, as if it never happened (it stays in the audit trail)."""
    from apps.drivers import services as drivers
    from apps.riders import services as riders

    now = now or timezone.now()
    recent = Ban.objects.filter(user=user, lifted_at__isnull=True, banned_at__gte=now - UNDO_WINDOW)
    if not recent.exists():
        raise BusinessRuleViolation("A ban can only be undone in the first 10 minutes.")
    n = recent.update(lifted_at=now, lift_reason=f"Undone by {actor.get_full_name()}")
    driver = getattr(user, "driver_profile", None)
    rider = getattr(user, "rider_profile", None)
    if driver and driver.onboarding_status == "SUSPENDED":
        drivers.reinstate_driver(driver, actor=actor)
    if rider and rider.is_blocked:
        riders.set_blocked(rider, False, actor=actor)
    _audit(user, "Ban undone within 10 minutes", actor)
    return n
