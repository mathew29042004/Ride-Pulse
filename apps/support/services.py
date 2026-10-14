from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.roles import Cap
from apps.audit.services import log_transition
from apps.core.conf import ticket_sla_hours
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify, notify_role
from apps.realtime import broadcast

from .models import (
    CATEGORY_PRIORITY,
    OPEN_TICKET_STATUSES,
    IncidentStatus,
    SafetyIncident,
    SupportTicket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)

SOS_WINDOW_AFTER_TRIP = timedelta(minutes=30)


def least_loaded_agent():
    """Round-robin by load: the active support agent with the fewest open tickets."""
    return (
        get_user_model()
        .objects.filter(role=Role.SUPPORT_AGENT, is_active=True)
        .annotate(
            load=Count(
                "tickets_assigned", filter=Q(tickets_assigned__status__in=OPEN_TICKET_STATUSES)
            )
        )
        .order_by("load", "id")
        .first()
    )


def _ticket_link(ticket: SupportTicket, user) -> str:
    if user.is_rider:
        return f"/ride/support/{ticket.pk}/"
    if user.is_driver:
        return f"/drive/support/{ticket.pk}/"
    return f"/ops/support/{ticket.pk}/"


@transaction.atomic
def open_ticket(
    *,
    user,
    category: str,
    subject: str,
    description: str,
    trip=None,
    priority: str | None = None,
    now: datetime | None = None,
) -> SupportTicket:
    from apps.rides.services import can_view_trip

    now = now or timezone.now()
    if trip is not None and not can_view_trip(user, trip):
        raise ActionNotPermitted("You can only raise tickets about your own trips.")
    if category not in TicketCategory.values:
        raise BusinessRuleViolation("Choose a valid category.", field="category")
    priority = priority or CATEGORY_PRIORITY[category]
    agent = least_loaded_agent()
    ticket = SupportTicket.objects.create(
        ticket_number=next_reference("TKT", year=timezone.localtime(now).year),
        raised_by=user,
        trip=trip,
        category=category,
        priority=priority,
        subject=subject[:160],
        description=description,
        assigned_to=agent,
        sla_due_at=now + timedelta(hours=ticket_sla_hours(priority)),
    )
    if agent:
        notify(
            agent,
            f"New {ticket.get_priority_display().lower()} ticket {ticket.ticket_number}",
            subject,
            level=Level.DANGER if priority == TicketPriority.URGENT else Level.INFO,
            link=_ticket_link(ticket, agent),
        )
    return ticket


@transaction.atomic
def reply(ticket: SupportTicket, *, author, body: str, internal: bool = False) -> TicketMessage:
    if not body.strip():
        raise BusinessRuleViolation("Write a message.", field="body")
    is_staff = author.is_staff_member
    if not is_staff and author.pk != ticket.raised_by_id:
        raise ActionNotPermitted("You can't reply to this ticket.")
    if internal and not is_staff:
        raise ActionNotPermitted("Only staff can add internal notes.")
    if not ticket.is_open:
        raise InvalidStateTransition(
            "This ticket is closed. Open a new one if you still need help."
        )
    message = TicketMessage.objects.create(
        ticket=ticket, author=author, body=body, is_internal=internal
    )
    if not internal:
        ticket.status = TicketStatus.WAITING_ON_USER if is_staff else TicketStatus.IN_PROGRESS
        if is_staff and ticket.assigned_to_id is None:
            ticket.assigned_to = author
        ticket.save(update_fields=["status", "assigned_to", "updated_at"])
        recipient = ticket.raised_by if is_staff else ticket.assigned_to
        if recipient:
            notify(
                recipient,
                f"New reply on {ticket.ticket_number}",
                body[:200],
                link=_ticket_link(ticket, recipient),
                email=is_staff,
            )
    return message


@transaction.atomic
def assign(ticket: SupportTicket, *, agent, actor=None) -> SupportTicket:
    if not agent.is_staff_member:
        raise BusinessRuleViolation("Tickets can only be assigned to staff.")
    ticket.assigned_to = agent
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS
    ticket.save(update_fields=["assigned_to", "status", "updated_at"])
    notify(
        agent,
        f"{ticket.ticket_number} assigned to you",
        ticket.subject,
        link=_ticket_link(ticket, agent),
    )
    return ticket


@transaction.atomic
def resolve_ticket_quietly(ticket: SupportTicket, *, note: str) -> None:
    """Close a ticket the users sorted out themselves (e.g. a lost item handed back)."""
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    if not ticket.is_open:
        return
    previous = ticket.status
    ticket.status = TicketStatus.RESOLVED
    ticket.resolution = note
    ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["status", "resolution", "resolved_at", "updated_at"])
    log_transition(ticket, previous, TicketStatus.RESOLVED, actor=None, note=note)


@transaction.atomic
def resolve(
    ticket: SupportTicket, *, actor, resolution: str, refund_amount: Decimal | int | str = 0
) -> SupportTicket:
    from apps.payments.services import refund_to_wallet

    ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    if not ticket.is_open:
        raise InvalidStateTransition("This ticket is already resolved.")
    if not resolution.strip():
        raise BusinessRuleViolation("Describe the resolution.", field="resolution")
    refund = Decimal(str(refund_amount or 0))
    if refund > 0:
        if not actor.has_capability(Cap.PAYMENTS_REFUND):
            raise ActionNotPermitted("Your role can't issue refunds.")
        if ticket.trip is None:
            raise BusinessRuleViolation("Refunds need a trip on the ticket.", field="refund_amount")
        refund_to_wallet(
            ticket.trip, refund, reason=f"{ticket.ticket_number}: {resolution}", actor=actor
        )
    previous = ticket.status
    ticket.status = TicketStatus.RESOLVED
    ticket.resolution = resolution
    ticket.refund_amount = refund
    ticket.resolved_at = timezone.now()
    ticket.save(
        update_fields=["status", "resolution", "refund_amount", "resolved_at", "updated_at"]
    )
    log_transition(ticket, previous, TicketStatus.RESOLVED, actor=actor, note=resolution)
    notify(
        ticket.raised_by,
        f"{ticket.ticket_number} resolved",
        resolution + (f" ₹{refund} was refunded to your wallet." if refund else ""),
        level=Level.SUCCESS,
        link=_ticket_link(ticket, ticket.raised_by),
        email=True,
    )
    return ticket


def escalate_sla_breaches(*, now: datetime | None = None) -> int:
    now = now or timezone.now()
    overdue = list(
        SupportTicket.objects.filter(
            status__in=OPEN_TICKET_STATUSES, sla_due_at__lt=now, escalated=False
        )
    )
    for ticket in overdue:
        ticket.escalated = True
        ticket.save(update_fields=["escalated", "updated_at"])
        notify_role(
            Role.ASSOC_SUPPORT,
            f"SLA breached: {ticket.ticket_number}",
            f"{ticket.get_priority_display()} ticket open since {ticket.created_at:%d %b %H:%M}.",
            level=Level.DANGER,
            link=f"/ops/support/{ticket.pk}/",
        )
        notify_role(
            Role.OPS_MANAGER,
            f"SLA breached: {ticket.ticket_number}",
            f"{ticket.get_priority_display()} ticket open since {ticket.created_at:%d %b %H:%M}.",
            level=Level.DANGER,
            link=f"/ops/support/{ticket.pk}/",
        )
    return len(overdue)


# --- Safety ------------------------------------------------------------------------------


@transaction.atomic
def raise_sos(
    *,
    trip,
    user,
    lat: float | None = None,
    lng: float | None = None,
    note: str = "",
    ambulance: bool = False,
    now: datetime | None = None,
) -> SafetyIncident:
    from apps.rides.models import TripFlag, TripStatus

    now = now or timezone.now()
    on_trip = trip.rider.user_id == user.pk or (trip.driver_id and trip.driver.user_id == user.pk)
    if not on_trip:
        raise ActionNotPermitted("Only the rider or driver can raise an SOS on this trip.")
    recently_finished = (
        trip.status == TripStatus.COMPLETED
        and trip.completed_at
        and now - trip.completed_at <= SOS_WINDOW_AFTER_TRIP
    )
    if not (trip.is_active or recently_finished):
        raise InvalidStateTransition("SOS is available during a trip and for 30 minutes after it.")
    ticket = open_ticket(
        user=user,
        category=TicketCategory.SAFETY,
        subject=f"SOS on {trip.trip_number}",
        description=note or "SOS button pressed.",
        trip=trip,
        priority=TicketPriority.URGENT,
        now=now,
    )
    incident = SafetyIncident.objects.create(
        incident_number=next_reference("SOS", year=timezone.localtime(now).year),
        trip=trip,
        raised_by=user,
        lat=lat if lat is not None else trip.pickup_lat,
        lng=lng if lng is not None else trip.pickup_lng,
        note=note,
        ticket=ticket,
        ambulance_requested=ambulance,
    )
    if TripFlag.SOS not in trip.flags:
        trip.flags = [*trip.flags, TripFlag.SOS]
        trip.save(update_fields=["flags", "updated_at"])
    for role in (
        Role.OPS_MANAGER,
        Role.SUPPORT_AGENT,
        Role.ASSOC_RIDES,
        Role.ASSOC_SUPPORT,
        Role.ADMIN,
    ):
        notify_role(
            role,
            f"🚨 SOS on {trip.trip_number}" + (" · AMBULANCE NEEDED" if ambulance else ""),
            (
                "Medical emergency: dispatch an ambulance (108) to the trip's location. "
                if ambulance
                else ""
            )
            + (note or "Rider or driver pressed SOS. Call them now."),
            level=Level.DANGER,
            link=f"/ops/safety/{incident.pk}/",
        )
    broadcast.ops_event(
        "sos",
        {"incident_id": incident.pk, "trip_id": trip.pk, "lat": incident.lat, "lng": incident.lng},
    )
    return incident


@transaction.atomic
def acknowledge_incident(incident: SafetyIncident, *, actor) -> SafetyIncident:
    if incident.status != IncidentStatus.OPEN:
        raise InvalidStateTransition("This incident is already being handled.")
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_by = actor
    incident.acknowledged_at = timezone.now()
    incident.save(update_fields=["status", "acknowledged_by", "acknowledged_at", "updated_at"])
    notify(
        incident.raised_by,
        "Our safety team is on it",
        "An agent has seen your SOS and will call you right away.",
        level=Level.WARNING,
    )
    return incident


@transaction.atomic
def resolve_incident(incident: SafetyIncident, *, actor, note: str) -> SafetyIncident:
    if incident.status == IncidentStatus.RESOLVED:
        raise InvalidStateTransition("This incident is already resolved.")
    if not note.strip():
        raise BusinessRuleViolation("Add a resolution note.", field="note")
    if incident.status == IncidentStatus.OPEN:
        incident.acknowledged_by = actor
        incident.acknowledged_at = timezone.now()
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = timezone.now()
    incident.resolution_note = note
    incident.save()
    if incident.ticket and incident.ticket.is_open:
        resolve(incident.ticket, actor=actor, resolution=note)
    return incident
