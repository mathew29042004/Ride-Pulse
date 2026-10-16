"""Lost and found: a rider reports an item left in the car (up to 7 days after the ride); the
driver is alerted and answers found / not found; masked calls between them stay open for 24
hours after the report so they can arrange the hand-back without sharing numbers. A support
ticket tracks it for the operations team.

* Phones, wallets, keys and documents are **valuables**: their ticket is urgent.
* **Deliver it to me**: once found, the rider can have it brought to them as a bike parcel from
  wherever the driver is (paid like any parcel); it's marked returned when the parcel arrives.
* **Unclaimed**: a found item nobody collects within 7 days goes to the city hub (the driver
  drops it off; the rider can collect it there); after 30 days at the hub it's donated, with
  notice to the rider. A driver who hasn't answered in 12 hours gets a reminder.
"""

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

from .models import LostItemCategory, LostItemReport, LostItemStatus, Trip, TripStatus

REPORT_WINDOW = timedelta(days=7)
CALL_WINDOW = timedelta(hours=24)
HUB_AFTER = timedelta(days=7)
DISPOSE_AFTER = timedelta(days=30)
REMIND_AFTER = timedelta(hours=12)
VALUABLES = {
    LostItemCategory.PHONE,
    LostItemCategory.WALLET,
    LostItemCategory.KEYS,
    LostItemCategory.DOCUMENTS,
}


@transaction.atomic
def report(
    trip: Trip, *, user, description: str, category: str = LostItemCategory.OTHER
) -> LostItemReport:
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
    if category not in LostItemCategory.values:
        raise BusinessRuleViolation("Choose what you lost.", field="category")
    if LostItemReport.objects.filter(trip=trip).exists():
        raise ConflictError("You've already reported a lost item for this ride.")
    valuable = category in VALUABLES
    ticket = open_ticket(
        user=user,
        category=TicketCategory.LOST_ITEM,
        subject=f"Lost {LostItemCategory(category).label.lower()}: {description[:50]}",
        description=description,
        trip=trip,
        priority=TicketPriority.URGENT if valuable else TicketPriority.HIGH,
    )
    item = LostItemReport.objects.create(
        trip=trip, description=description, category=category, ticket=ticket
    )
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
    item.found_at = timezone.now() if found else None
    item.save(update_fields=["status", "driver_note", "found_at", "updated_at"])
    driver_name = trip.driver.user.first_name or "Your driver"
    notify(
        trip.rider.user,
        f"{driver_name} found your {item.description}"
        if found
        else f"{driver_name} couldn't find your item",
        (note + " " if note else "")
        + (
            "Call them from the trip, or have it delivered to you as a parcel."
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
    staff = getattr(user, "is_staff_member", False) or user.is_staff
    if user.pk not in (trip.rider.user_id, trip.driver.user_id) and not staff:
        raise ActionNotPermitted("Only the rider or driver can mark it returned.")
    if item.status not in (LostItemStatus.FOUND, LostItemStatus.AT_HUB, LostItemStatus.ON_THE_WAY):
        raise InvalidStateTransition("Only found items can be marked returned.")
    item.status, item.closed_at = LostItemStatus.RETURNED, timezone.now()
    item.save(update_fields=["status", "closed_at", "updated_at"])
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


# --- Delivery to the rider, the hub, and reminders --------------------------------------------


def request_delivery(
    item: LostItemReport,
    *,
    user,
    dropoff: tuple[float, float],
    dropoff_address: str = "",
    payment_method: str = "UPI",
    now=None,
) -> Trip:
    """Book a bike parcel from where the driver is to the rider (the rider pays the parcel)."""
    from apps.pricing.models import RideType

    from . import services as rides

    now = now or timezone.now()
    item = LostItemReport.objects.select_related("trip__driver__user", "trip__rider__user").get(
        pk=item.pk
    )
    trip = item.trip
    if trip.rider.user_id != user.pk:
        raise ActionNotPermitted("Only the rider can ask for delivery.")
    if item.status != LostItemStatus.FOUND:
        raise InvalidStateTransition("Delivery is possible once the driver has found it.")
    driver = trip.driver
    if driver.current_lat is None:
        raise BusinessRuleViolation("We can't see where the driver is; call them to arrange it.")
    rider = trip.rider
    parcel = rides.request_trip(
        rider=rider,
        ride_type=RideType.objects.get(code="PARCEL"),
        pickup=(driver.current_lat, driver.current_lng),
        dropoff=dropoff,
        pickup_address=f"From {driver.name} (your driver on {trip.trip_number})",
        dropoff_address=dropoff_address,
        payment_method=payment_method,
        parcel={
            "recipient_name": rider.name,
            "recipient_phone": rider.user.phone,
            "category": "OTHER",
            "weight_kg": 1,
            "instructions": f"Lost item: {item.description}"[:200],
        },
        now=now,
    )
    LostItemReport.objects.filter(pk=item.pk).update(
        status=LostItemStatus.ON_THE_WAY, return_trip=parcel, updated_at=now
    )
    notify(
        driver.user,
        "A courier is coming for the lost item",
        f"Please hand over “{item.description}” to the parcel partner for {parcel.trip_number}.",
        level=Level.INFO,
        link="/drive",
    )
    return parcel


def on_trip_finished(trip: Trip) -> None:
    """A return parcel was delivered (item returned) or cancelled (back to found)."""
    item = LostItemReport.objects.filter(return_trip=trip).first()
    if item is None:
        return
    if trip.status == TripStatus.COMPLETED:
        from apps.support.services import resolve_ticket_quietly

        LostItemReport.objects.filter(pk=item.pk).update(
            status=LostItemStatus.RETURNED, closed_at=timezone.now()
        )
        if item.ticket_id:
            resolve_ticket_quietly(item.ticket, note="Delivered back to the rider by parcel.")
    elif trip.status in (TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND):
        LostItemReport.objects.filter(pk=item.pk).update(
            status=LostItemStatus.FOUND, return_trip=None
        )


def to_hub(item: LostItemReport, *, now=None) -> LostItemReport:
    now = now or timezone.now()
    item.status, item.hub_at = LostItemStatus.AT_HUB, now
    item.save(update_fields=["status", "hub_at", "updated_at"])
    trip = item.trip
    notify(
        trip.driver.user,
        "Please drop the lost item at the hub",
        f"“{item.description}” from {trip.trip_number} wasn't collected. Drop it at the "
        f"{trip.city.name} Ride Pulse hub on your next visit.",
        level=Level.INFO,
        link="/drive",
    )
    notify(
        trip.rider.user,
        f"Your {item.description} is at our {trip.city.name} hub",
        "Collect it within 30 days with your ID, or ask support to deliver it.",
        level=Level.INFO,
        link=f"/ride/trips/{trip.pk}/",
    )
    return item


def dispose(item: LostItemReport, *, now=None) -> LostItemReport:
    now = now or timezone.now()
    item.status, item.closed_at = LostItemStatus.DISPOSED, now
    item.save(update_fields=["status", "closed_at", "updated_at"])
    notify(
        item.trip.rider.user,
        f"Your {item.description} was donated",
        "It stayed unclaimed at our hub for 30 days. Contact support if this is a mistake.",
        level=Level.WARNING,
    )
    return item


def sweep(*, now=None) -> dict:
    """Daily: remind drivers, move uncollected items to the hub, donate long-unclaimed ones."""
    now = now or timezone.now()
    counts = {"reminded": 0, "to_hub": 0, "disposed": 0}
    for item in LostItemReport.objects.filter(
        status=LostItemStatus.REPORTED, created_at__lte=now - REMIND_AFTER
    ).select_related("trip__driver__user"):
        title = "Reminder: a rider is waiting about a lost item"
        from apps.notifications.models import Notification

        if not Notification.objects.filter(user=item.trip.driver.user, title=title).exists():
            notify(
                item.trip.driver.user,
                title,
                f"“{item.description}” from {item.trip.trip_number}.",
                level=Level.WARNING,
                link="/drive",
            )
            counts["reminded"] += 1
    for item in LostItemReport.objects.filter(
        status=LostItemStatus.FOUND, found_at__lte=now - HUB_AFTER
    ).select_related("trip__driver__user", "trip__rider__user", "trip__city"):
        to_hub(item, now=now)
        counts["to_hub"] += 1
    for item in LostItemReport.objects.filter(
        status=LostItemStatus.AT_HUB, hub_at__lte=now - DISPOSE_AFTER
    ).select_related("trip__rider__user"):
        dispose(item, now=now)
        counts["disposed"] += 1
    return counts
