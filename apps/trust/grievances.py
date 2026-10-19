"""The grievance officer's desk, as the Motor Vehicle Aggregator Guidelines and the consumer
protection (e-commerce) rules require: a named grievance officer, published contact details, a
written acknowledgement within 48 hours and a resolution within 15 days.

* Riders and drivers file a grievance from the app (anything: fares, a driver's or rider's
  conduct, a suspension, earnings and commission, discrimination, safety). It's separate from a
  support ticket: it's the formal route, tracked against the legal deadlines.
* The grievance team acknowledges it (the clock to acknowledge stops), investigates and resolves
  it in writing.
* Not acknowledged in 48 hours, or not resolved in 15 days: it escalates to the appellate officer
  (a regional manager) automatically, and the person is told.
* Unhappy with the resolution? The person can escalate it once, and is told they may also
  approach the state transport authority or consumer forum.
* The compliance dashboard shows how many were acknowledged and resolved on time.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition

ACK_WITHIN = timedelta(hours=48)
RESOLVE_WITHIN = timedelta(days=15)
OFFICER = {
    "name": "Lakshmi Narayanan",
    "title": "Grievance Officer",
    "email": "grievance@ridepulse.in",
    "phone": "1800-200-7788",
    "hours": "Monday to Saturday, 9 am – 6 pm",
    "address": "Ride Pulse Mobility Pvt Ltd, 4th Floor, Olympia Tech Park, Guindy, Chennai 600032",
}


class GrievanceCategory(models.TextChoices):
    FARE = "FARE", "Fare or charges"
    CONDUCT = "CONDUCT", "Conduct of a driver or rider"
    SAFETY = "SAFETY", "Safety"
    ACCOUNT = "ACCOUNT", "Account suspended or blocked"
    EARNINGS = "EARNINGS", "Earnings, commission or payouts"
    DISCRIMINATION = "DISCRIM", "Discrimination"
    SERVICE = "SERVICE", "Service quality"
    OTHER = "OTHER", "Something else"


class GrievanceStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged · being looked into"
    RESOLVED = "RESOLVED", "Resolved"
    ESCALATED = "ESCALATED", "With the appellate officer"
    CLOSED = "CLOSED", "Closed"


class Grievance(models.Model):
    number = models.CharField(max_length=20, unique=True)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grievances"
    )
    category = models.CharField(max_length=8, choices=GrievanceCategory.choices)
    subject = models.CharField(max_length=140)
    description = models.TextField(max_length=4000)
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(
        max_length=12, choices=GrievanceStatus.choices, default=GrievanceStatus.RECEIVED
    )
    created_at = models.DateTimeField()
    ack_due = models.DateTimeField()
    resolve_due = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_reason = models.CharField(max_length=200, blank=True)
    appellate_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    satisfied = models.BooleanField(null=True, blank=True)

    class Meta:
        app_label = "trust"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "ack_due"], name="grievance_queue_idx")]

    def __str__(self) -> str:
        return f"{self.number}: {self.subject}"


def _notify(user, title: str, body: str, *, link: str):
    from apps.notifications.services import notify

    notify(user, title, body, link=link)


def _link(user) -> str:
    return "/drive/grievances" if getattr(user, "is_driver", False) else "/ride/grievances"


def file(user, *, category: str, subject: str, description: str, trip=None, now=None) -> Grievance:
    from apps.core.sequences import next_reference
    from apps.rides.services import can_view_trip

    now = now or timezone.now()
    if not (getattr(user, "is_rider", False) or getattr(user, "is_driver", False)):
        raise ActionNotPermitted("Grievances are for riders and drivers.")
    if category not in GrievanceCategory.values:
        raise BusinessRuleViolation("Choose what it's about.", field="category")
    if len(subject.strip()) < 5:
        raise BusinessRuleViolation("Give it a short title.", field="subject")
    if len(description.strip()) < 20:
        raise BusinessRuleViolation("Tell us what happened (a few sentences).", field="description")
    if trip is not None and not can_view_trip(user, trip):
        raise ActionNotPermitted("You can only refer to your own trips.")
    open_count = (
        Grievance.objects.filter(raised_by=user)
        .exclude(status__in=[GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED])
        .count()
    )
    if open_count >= 5:
        raise BusinessRuleViolation("You have 5 open grievances. We'll answer those first.")
    g = Grievance.objects.create(
        number=next_reference("GRV", year=timezone.localtime(now).year),
        raised_by=user,
        category=category,
        subject=subject.strip()[:140],
        description=description.strip()[:4000],
        trip=trip,
        created_at=now,
        ack_due=now + ACK_WITHIN,
        resolve_due=now + RESOLVE_WITHIN,
    )
    _notify(
        user,
        f"Grievance {g.number} received",
        f"Our grievance officer will acknowledge it within 48 hours and resolve it within 15 days "
        f"(by {timezone.localtime(g.resolve_due):%d %b}).",
        link=_link(user),
    )
    return g


def acknowledge(g: Grievance, *, user, now=None) -> Grievance:
    if g.status != GrievanceStatus.RECEIVED:
        raise InvalidStateTransition("Already acknowledged.")
    g.status, g.acknowledged_at, g.handled_by = (
        GrievanceStatus.ACKNOWLEDGED,
        now or timezone.now(),
        user,
    )
    g.save(update_fields=["status", "acknowledged_at", "handled_by"])
    _notify(
        g.raised_by,
        f"Grievance {g.number} acknowledged",
        f"{user.get_full_name()} is looking into it. You'll have a written answer by "
        f"{timezone.localtime(g.resolve_due):%d %b}.",
        link=_link(g.raised_by),
    )
    return g


def resolve(g: Grievance, *, user, resolution: str, now=None) -> Grievance:
    if g.status in (GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED):
        raise InvalidStateTransition("Already resolved.")
    if len(resolution.strip()) < 20:
        raise BusinessRuleViolation(
            "Write the resolution: what you found and what was done.", field="resolution"
        )
    now = now or timezone.now()
    g.acknowledged_at = g.acknowledged_at or now
    g.status, g.resolved_at, g.resolution = GrievanceStatus.RESOLVED, now, resolution.strip()
    g.handled_by = g.handled_by or user
    g.save(update_fields=["status", "acknowledged_at", "resolved_at", "resolution", "handled_by"])
    _notify(
        g.raised_by,
        f"Grievance {g.number} resolved",
        resolution.strip()[:200],
        link=_link(g.raised_by),
    )
    return g


def _appellate():
    from apps.accounts.models import Role, User

    return User.objects.filter(role=Role.REGIONAL_MANAGER, is_active=True).order_by("pk").first()


def escalate(g: Grievance, *, reason: str, by=None, now=None) -> Grievance:
    """To the appellate officer: by the person (once, after a resolution) or automatically when
    late."""
    now = now or timezone.now()
    if by is not None:
        if by.pk != g.raised_by_id:
            raise ActionNotPermitted("Only the person who raised it can escalate it.")
        if g.status != GrievanceStatus.RESOLVED or g.escalated_at:
            raise InvalidStateTransition("You can escalate once, after the grievance is resolved.")
        if len(reason.strip()) < 10:
            raise BusinessRuleViolation("Say why the resolution isn't right.", field="reason")
        g.satisfied = False
    g.status, g.escalated_at = GrievanceStatus.ESCALATED, now
    g.escalation_reason = reason.strip()[:200]
    g.appellate_officer = _appellate()
    g.resolve_due = now + RESOLVE_WITHIN
    g.save(
        update_fields=[
            "status",
            "escalated_at",
            "escalation_reason",
            "appellate_officer",
            "resolve_due",
            "satisfied",
        ]
    )
    if g.appellate_officer:
        _notify(
            g.appellate_officer,
            f"Grievance {g.number} escalated to you",
            g.escalation_reason,
            link="/ops/grievances",
        )
    _notify(
        g.raised_by,
        f"Grievance {g.number} escalated",
        "The appellate officer will review it within 15 days. You may also approach your state "
        "transport authority or the consumer commission at any time.",
        link=_link(g.raised_by),
    )
    return g


def rate(g: Grievance, *, user, satisfied: bool) -> Grievance:
    if user.pk != g.raised_by_id or g.status != GrievanceStatus.RESOLVED:
        raise ActionNotPermitted("You can rate your own resolved grievances.")
    g.satisfied = satisfied
    if satisfied:
        g.status = GrievanceStatus.CLOSED
    g.save(update_fields=["satisfied", "status"])
    return g


def sweep(*, now=None) -> dict:
    """Hourly: escalate grievances that missed the 48-hour or 15-day deadline."""
    now = now or timezone.now()
    late_ack = Grievance.objects.filter(status=GrievanceStatus.RECEIVED, ack_due__lt=now)
    late_fix = Grievance.objects.filter(status=GrievanceStatus.ACKNOWLEDGED, resolve_due__lt=now)
    stats = {"late_acknowledgement": 0, "late_resolution": 0}
    for g in late_ack:
        escalate(g, reason="Not acknowledged within 48 hours", now=now)
        stats["late_acknowledgement"] += 1
    for g in late_fix:
        escalate(g, reason="Not resolved within 15 days", now=now)
        stats["late_resolution"] += 1
    return stats


def row(g: Grievance, *, now=None) -> dict:
    now = now or timezone.now()
    open_ = g.status in (
        GrievanceStatus.RECEIVED,
        GrievanceStatus.ACKNOWLEDGED,
        GrievanceStatus.ESCALATED,
    )
    return {
        "id": g.pk,
        "number": g.number,
        "category": g.category,
        "category_label": g.get_category_display(),
        "subject": g.subject,
        "description": g.description,
        "status": g.status,
        "status_label": g.get_status_display(),
        "created_at": g.created_at,
        "ack_due": g.ack_due,
        "resolve_due": g.resolve_due,
        "acknowledged_at": g.acknowledged_at,
        "resolved_at": g.resolved_at,
        "resolution": g.resolution,
        "escalated_at": g.escalated_at,
        "escalation_reason": g.escalation_reason,
        "satisfied": g.satisfied,
        "trip_number": g.trip.trip_number if g.trip_id else None,
        "raised_by": g.raised_by.get_full_name(),
        "who": "Driver" if getattr(g.raised_by, "is_driver", False) else "Rider",
        "handled_by": g.handled_by.get_full_name() if g.handled_by_id else None,
        "appellate_officer": g.appellate_officer.get_full_name()
        if g.appellate_officer_id
        else None,
        "overdue": open_
        and ((g.status == GrievanceStatus.RECEIVED and g.ack_due < now) or g.resolve_due < now),
    }


def compliance(*, days: int = 90, now=None) -> dict:
    """On-time rates for the compliance dashboard."""
    now = now or timezone.now()
    rows = list(Grievance.objects.filter(created_at__gte=now - timedelta(days=days)))
    acked = [g for g in rows if g.acknowledged_at]
    resolved = [g for g in rows if g.resolved_at]
    on_time_ack = sum(1 for g in acked if g.acknowledged_at <= g.created_at + ACK_WITHIN)
    on_time_fix = sum(1 for g in resolved if g.resolved_at <= g.created_at + RESOLVE_WITHIN)
    return {
        "received": len(rows),
        "open": sum(1 for g in rows if g.status in ("RECEIVED", "ACKNOWLEDGED", "ESCALATED")),
        "ack_on_time_pct": round(100 * on_time_ack / len(acked)) if acked else None,
        "resolved_on_time_pct": round(100 * on_time_fix / len(resolved)) if resolved else None,
        "escalated": sum(1 for g in rows if g.escalated_at),
    }
