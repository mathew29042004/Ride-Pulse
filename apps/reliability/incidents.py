"""Incidents and the public status page.

Ops open an incident when part of the service breaks, choose what's affected, and post updates.
Riders and drivers see the public message as a banner; ``/status`` shows every component and
recent incidents to anyone; updates go to the #operations team channel. After it's resolved,
ops write a blameless review (what happened, the root cause) and the follow-up actions become
tasks for named people.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference

from . import fallbacks
from .models import Component, Incident, IncidentSeverity, IncidentStatus, IncidentUpdate

ORDER = [IncidentStatus.INVESTIGATING, IncidentStatus.IDENTIFIED, IncidentStatus.MONITORING]
STATE = {
    IncidentSeverity.MINOR: "DEGRADED",
    IncidentSeverity.MAJOR: "PARTIAL",
    IncidentSeverity.CRITICAL: "OUTAGE",
}
RANK = {"OPERATIONAL": 0, "DEGRADED": 1, "PARTIAL": 2, "OUTAGE": 3}


def _post_to_ops_channel(text: str) -> None:
    from apps.chat.models import Conversation, Message

    channel = Conversation.objects.filter(kind="CHANNEL", slug="operations").first()
    if channel is None:
        return
    now = timezone.now()
    message = Message.objects.create(conversation=channel, body=text, created_at=now)
    Conversation.objects.filter(pk=channel.pk).update(last_message_at=now)
    from apps.chat.services import _deliver

    _deliver(channel, message)


@transaction.atomic
def open_incident(
    *, user, title: str, severity: str, components: list[str], public_message: str, now=None
) -> Incident:
    now = now or timezone.now()
    components = [c for c in components if c in Component.values]
    if not components:
        raise BusinessRuleViolation("Choose what's affected.", field="components")
    if severity not in IncidentSeverity.values:
        raise BusinessRuleViolation("Choose how bad it is.", field="severity")
    if len(public_message.strip()) < 10:
        raise BusinessRuleViolation(
            "Write what riders and drivers should know.", field="public_message"
        )
    incident = Incident.objects.create(
        number=next_reference("INC", year=now.year, width=4),
        title=title.strip()[:160],
        severity=severity,
        components=components,
        public_message=public_message.strip()[:240],
        started_at=now,
        created_by=user,
    )
    IncidentUpdate.objects.create(
        incident=incident, status=incident.status, message=incident.public_message, at=now, by=user
    )
    labels = ", ".join(Component(c).label for c in components)
    _post_to_ops_channel(
        f"🔴 {incident.number} opened ({incident.get_severity_display()}): {incident.title}. "
        f"Affects: {labels}."
    )
    fallbacks.forget()  # payments or maps may switch to (or out of) a fallback
    if severity != IncidentSeverity.MINOR:
        open_war_room(incident, now=now)
        from .briefing import system_update

        system_update(
            f"{incident.number} {incident.get_severity_display().lower()} incident: "
            f"{incident.title}",
            f"Affects {labels}. {incident.public_message}",
            source="Platform & incidents",
            urgent=severity == IncidentSeverity.CRITICAL,
        )
    return incident


@transaction.atomic
def update(
    incident: Incident, *, user, status: str, message: str, public_message: str = "", now=None
) -> Incident:
    now = now or timezone.now()
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if incident.status == IncidentStatus.RESOLVED:
        raise InvalidStateTransition("This incident is resolved.")
    if status not in IncidentStatus.values:
        raise BusinessRuleViolation("Unknown status.", field="status")
    if len(message.strip()) < 5:
        raise BusinessRuleViolation("Say what changed.", field="message")
    incident.status = status
    if public_message.strip():
        incident.public_message = public_message.strip()[:240]
    if status == IncidentStatus.RESOLVED:
        incident.resolved_at = now
    incident.save()
    IncidentUpdate.objects.create(
        incident=incident, status=status, message=message.strip()[:500], at=now, by=user
    )
    icon = "✅" if status == IncidentStatus.RESOLVED else "🟠"
    post_to_war_room(
        incident,
        f"{icon} {incident.get_status_display()}: {message.strip()}",
        closing=status == IncidentStatus.RESOLVED,
        now=now,
    )
    _post_to_ops_channel(
        f"{icon} {incident.number} {incident.get_status_display().lower()}: {message.strip()}"
    )
    fallbacks.forget()  # payments or maps may switch to (or out of) a fallback
    return incident


@transaction.atomic
def review(
    incident: Incident, *, user, summary: str, root_cause: str, actions: list[dict], now=None
):
    """The blameless review: each action becomes a task for the named person."""
    from apps.workspace.services import create_tasks

    now = now or timezone.now()
    if incident.status != IncidentStatus.RESOLVED:
        raise InvalidStateTransition("Write the review after the incident is resolved.")
    if len(summary.strip()) < 20 or len(root_cause.strip()) < 10:
        raise BusinessRuleViolation("Describe what happened and the root cause.")
    incident.summary, incident.root_cause, incident.reviewed_at = (
        summary.strip(),
        root_cause.strip(),
        now,
    )
    incident.save(update_fields=["summary", "root_cause", "reviewed_at"])
    tasks = []
    for action in actions[:10]:
        title = str(action.get("title", "")).strip()
        if not title or not action.get("assignee_id"):
            continue
        tasks += create_tasks(
            manager=user,
            title=f"{incident.number}: {title}"[:160],
            due_at=now + timedelta(days=int(action.get("days", 7))),
            assignee_ids=[int(action["assignee_id"])],
            description=f"Follow-up from the review of {incident.number} ({incident.title}).",
            now=now,
        )
    return incident, tasks


def status_page(*, now=None) -> dict:
    """Public: each component's state, open incidents, and the last 14 days."""
    now = now or timezone.now()
    open_ = list(
        Incident.objects.exclude(status=IncidentStatus.RESOLVED).prefetch_related("updates")
    )
    states = dict.fromkeys(Component.values, "OPERATIONAL")
    for incident in open_:
        for c in incident.components:
            if RANK[STATE[incident.severity]] > RANK[states.get(c, "OPERATIONAL")]:
                states[c] = STATE[incident.severity]
    recent = Incident.objects.filter(started_at__gte=now - timedelta(days=14)).prefetch_related(
        "updates"
    )

    def row(i: Incident) -> dict:
        return {
            "number": i.number,
            "title": i.title,
            "severity": i.severity,
            "status": i.status,
            "status_label": i.get_status_display(),
            "components": i.components,
            "message": i.public_message,
            "started_at": i.started_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "updates": [
                {"status": u.get_status_display(), "message": u.message, "at": u.at.isoformat()}
                for u in i.updates.all()
            ],
        }

    return {
        "overall": max(states.values(), key=lambda s: RANK[s]),
        "components": [
            {"key": c, "label": Component(c).label, "state": states[c]} for c in Component.values
        ],
        "open": [row(i) for i in open_],
        "recent": [row(i) for i in recent if i.status == IncidentStatus.RESOLVED],
    }


def banner_for(user) -> dict | None:
    """The most serious open incident that touches this person's app."""
    relevant = {Component.BOOKING, Component.PAYMENTS, Component.MAPS, Component.NOTIFICATIONS}
    if getattr(user, "is_driver", False):
        relevant.add(Component.DRIVER_APP)
    rank = {IncidentSeverity.CRITICAL: 0, IncidentSeverity.MAJOR: 1, IncidentSeverity.MINOR: 2}
    best = sorted(
        (
            i
            for i in Incident.objects.exclude(status=IncidentStatus.RESOLVED)
            if set(i.components) & relevant
        ),
        key=lambda i: rank[i.severity],
    )
    if not best:
        from . import weather

        return weather.banner(_city_of(user))
    i = best[0]
    return {
        "number": i.number,
        "severity": i.severity,
        "message": i.public_message,
        "status": i.get_status_display(),
    }


def _city_of(user):
    """A driver's city, or for a rider the city of their latest trip (riders have no home city)."""
    if getattr(user, "is_driver", False):
        profile = getattr(user, "driver_profile", None)
        return profile.city if profile else None
    from apps.rides.models import Trip

    trip = (
        Trip.objects.filter(rider__user=user)
        .select_related("city")
        .order_by("-requested_at")
        .first()
    )
    return trip.city if trip else None


# --- War room ----------------------------------------------------------------------------------


def _numbers() -> str:
    from apps.analytics.services import live_status

    live = live_status()
    return (
        f"{live['drivers_online'] + live['drivers_on_trip']} drivers live, "
        f"{live['active_trips']} trips running, {live['searching']} riders waiting, "
        f"{live['open_tickets']} tickets open"
    )


def open_war_room(incident: Incident, *, now=None):
    """A chat room for a major or critical incident: whoever opened it, the commander and chief
    of staff, administrators and the city operations managers. Every update is posted in it, with
    the live numbers at the start and at the end."""
    from apps.accounts.models import Role, User
    from apps.chat.models import Conversation, ConversationKind
    from apps.chat.services import _add, _deliver, _system

    now = now or timezone.now()
    room, created = Conversation.objects.get_or_create(
        incident=incident,
        defaults={
            "kind": ConversationKind.INCIDENT,
            "name": f"{incident.number}: {incident.title}"[:80],
            "topic": "War room",
            "created_at": now,
        },
    )
    if created:
        people = set(
            User.objects.filter(
                is_active=True,
                staff_profile__isnull=False,
                role__in=[Role.COMMANDER, Role.CHIEF_OF_STAFF, Role.ADMIN, Role.OPS_MANAGER],
            ).values_list("pk", flat=True)
        )
        if incident.created_by_id:
            people.add(incident.created_by_id)
        _add(room, people, now)
        _deliver(
            room,
            _system(
                room,
                f"🚨 War room for {incident.number}. Live numbers at the start: {_numbers()}.",
                now,
            ),
        )
    return room


def post_to_war_room(incident: Incident, text: str, *, closing: bool = False, now=None) -> None:
    from apps.chat.models import Conversation
    from apps.chat.services import _deliver, _system

    room = Conversation.objects.filter(incident=incident).first()
    if room is None:
        return
    now = now or timezone.now()
    _deliver(
        room, _system(room, text + (f" Live numbers now: {_numbers()}." if closing else ""), now)
    )
