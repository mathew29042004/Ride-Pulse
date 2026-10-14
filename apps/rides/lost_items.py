"""Lost and found: a rider reports an item left in the car (up to 7 days after the ride); the
driver is alerted and answers found / not found; masked calls between them stay open for 24
hours after the report so they can arrange the hand-back without sharing numbers. A support
ticket tracks it for the operations team."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    InvalidStateTransition,
)
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import LostItemReport, LostItemStatus, Trip, TripStatus

REPORT_WINDOW = timedelta(days=7)
CALL_WINDOW = timedelta(hours=24)


@transaction.atomic
def report(trip: Trip, *, user, description: str) -> LostItemReport:
    from apps.support.models import TicketCategory, TicketPriority
    from apps.support.services import open_ticket

    if not (user.is_rider and trip.rider.user_id == user.pk):
        raise ActionNotPermitted("Only the rider can report a lost item.")
    if trip.status != TripStatus.COMPLETED or trip.driver_id is None:
        raise InvalidStateTransition("You can report lost items after a completed ride.")
    if timezone.now() - trip.completed_at > REPORT_WINDOW:
        raise BusinessRuleViolation(
            "Lost items can be reported for 7 days. Please contact support."
        )
    description = " ".join(description.split())[:300]
    if len(description) < 3:
        raise BusinessRuleViolation("Describe the item (e.g. black backpack).", field="description")
    if LostItemReport.objects.filter(trip=trip).exists():
        raise ConflictError("You've already reported a lost item for this ride.")
    ticket = open_ticket(
        user=user,
        category=TicketCategory.LOST_ITEM,
        subject=f"Lost item: {description[:60]}",
        description=description,
        trip=trip,
        priority=TicketPriority.HIGH,
    )
    item = LostItemReport.objects.create(trip=trip, description=description, ticket=ticket)
    notify(
        trip.driver.user,
        "Your rider left something in your car",
        f"“{description}” from {trip.trip_number}. Please check and let them know in the app.",
        level=Level.WARNING,
        link="/drive",
    )
    return item


@transaction.atomic
def driver_answer(item: LostItemReport, *, user, found: bool, note: str = "") -> LostItemReport:
    item = (
        LostItemReport.objects.select_for_update(of=("self",))
        .select_related("trip__driver__user", "trip__rider__user")
        .get(pk=item.pk)
    )
    trip = item.trip
    if not (user.is_driver and trip.driver.user_id == user.pk):
        raise ActionNotPermitted("Only the trip's driver can answer.")
    if item.status not in (LostItemStatus.REPORTED, LostItemStatus.NOT_FOUND, LostItemStatus.FOUND):
        raise InvalidStateTransition("This report is closed.")
    item.status = LostItemStatus.FOUND if found else LostItemStatus.NOT_FOUND
    item.driver_note = note[:300]
    item.save(update_fields=["status", "driver_note", "updated_at"])
    driver_name = trip.driver.user.first_name or "Your driver"
    notify(
        trip.rider.user,
        f"{driver_name} found your {item.description}"
        if found
        else f"{driver_name} couldn't find your item",
        (note + " " if note else "")
        + (
            "Call them from the trip to arrange the hand-back."
            if found
            else "Our support team will follow up."
        ),
        level=Level.SUCCESS if found else Level.WARNING,
        link=f"/ride/trips/{trip.pk}/",
    )
    return item


@transaction.atomic
def mark_returned(item: LostItemReport, *, user) -> LostItemReport:
    from apps.support.services import resolve_ticket_quietly

    item = (
        LostItemReport.objects.select_for_update(of=("self",))
        .select_related("trip__driver", "trip__rider")
        .get(pk=item.pk)
    )
    trip = item.trip
    if user.pk not in (trip.rider.user_id, trip.driver.user_id):
        raise ActionNotPermitted("Only the rider or driver can mark it returned.")
    if item.status != LostItemStatus.FOUND:
        raise InvalidStateTransition("Only found items can be marked returned.")
    item.status = LostItemStatus.RETURNED
    item.save(update_fields=["status", "updated_at"])
    if item.ticket_id:
        resolve_ticket_quietly(item.ticket, note="Item returned to the rider.")
    return item


def calls_open(trip: Trip) -> bool:
    """Masked calls stay open for 24 h after a lost-item report that isn't closed."""
    item = LostItemReport.objects.filter(trip=trip).first()
    return bool(
        item
        and item.status in (LostItemStatus.REPORTED, LostItemStatus.FOUND)
        and timezone.now() - item.created_at < CALL_WINDOW
    )
