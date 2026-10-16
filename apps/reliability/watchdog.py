"""The trip watchdog: trips that stopped moving don't stay "active" forever.

A phone dies, the app is killed, a driver goes home without ending the trip: in real life some
trips are abandoned half-way. Left alone they block the rider and the driver (one active trip
each), keep showing on the live map and distort every metric. Every few minutes the watchdog
looks for trips whose driver's app has also gone silent:

* **Assigned, never arrived** (45 min): back to dispatch so the rider gets another driver; if
  the request is over 3 hours old it's closed instead (nobody is still waiting).
* **Arrived, never started** (60 min): closed with no fee.
* **Started, never finished**: three times the expected duration plus an hour (whole days for
  rentals, outstation and tours), and no location from the driver for 30 minutes: closed with
  no charge to the rider, flagged ABANDONED, with a support ticket to follow up.
* **Requested, deadline passed** (normally the dispatcher's job): expired.

Ops get one summary notification per run that closed anything.
"""

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Level
from apps.notifications.services import notify_role
from apps.rides.models import Trip, TripFlag, TripStatus

from .jobs import tracked

logger = logging.getLogger(__name__)

ASSIGNED_LIMIT = timedelta(minutes=45)
ARRIVED_LIMIT = timedelta(minutes=60)
SILENT = timedelta(minutes=15)
SILENT_IN_RIDE = timedelta(minutes=30)
TOO_OLD_TO_REASSIGN = timedelta(hours=3)


def _system_user():
    from apps.accounts.models import User

    return User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()


def _silent(trip: Trip, now: datetime, limit: timedelta) -> bool:
    seen = trip.driver.location_updated_at if trip.driver_id else None
    return seen is None or now - seen > limit


def expected_end(trip: Trip) -> datetime:
    minutes = float(trip.estimated_duration_min or 30)
    if trip.service in ("RENTAL", "INTERCITY"):
        allowance = timedelta(days=max(1, trip.trip_days or 1)) + timedelta(hours=6)
        return trip.started_at + max(timedelta(minutes=minutes * 2), allowance)
    return trip.started_at + timedelta(minutes=minutes * 3 + 60)


@tracked("trip-watchdog", every=timedelta(minutes=5))
def sweep(*, now: datetime | None = None) -> dict:
    from apps.rides import services as rides

    now = now or timezone.now()
    ops = _system_user()
    counts = {"reassigned": 0, "closed": 0, "abandoned": 0, "expired": 0}
    if ops is None:
        return counts

    for trip in Trip.objects.filter(
        status=TripStatus.REQUESTED, dispatch_deadline__lt=now - timedelta(minutes=5)
    ):
        with transaction.atomic():
            locked = Trip.objects.select_for_update().get(pk=trip.pk)
            if locked.status == TripStatus.REQUESTED:
                rides.expire_request(locked, now=now)
                counts["expired"] += 1

    for trip in Trip.objects.filter(
        status=TripStatus.DRIVER_ASSIGNED, assigned_at__lt=now - ASSIGNED_LIMIT
    ).select_related("driver__user"):
        if _silent(trip, now, SILENT):
            _safely(_before_pickup, trip, ops, now, counts)

    for trip in Trip.objects.filter(
        status=TripStatus.DRIVER_ARRIVED, arrived_at__lt=now - ARRIVED_LIMIT
    ).select_related("driver"):
        if _silent(trip, now, SILENT):
            _safely(_never_started, trip, ops, now, counts)

    for trip in Trip.objects.filter(
        status=TripStatus.IN_PROGRESS, started_at__lt=now - timedelta(minutes=30)
    ).select_related("driver", "rider__user"):
        if now >= expected_end(trip) and _silent(trip, now, SILENT_IN_RIDE):
            _safely(_abandoned, trip, ops, now, counts)

    closed = counts["closed"] + counts["abandoned"] + counts["reassigned"]
    if closed:
        notify_role(
            "OPS_MANAGER",
            f"Trip watchdog closed {closed} stuck trip{'s' if closed != 1 else ''}",
            f"{counts['abandoned']} abandoned mid-ride (tickets opened), {counts['closed']} "
            f"closed before starting, {counts['reassigned']} sent to another driver.",
            level=Level.WARNING,
            link="/ops/trips",
        )
    return counts


def _safely(action, trip, ops, now, counts) -> bool:
    """One odd trip must never stop the watchdog: log it and carry on."""
    from apps.core.exceptions import DomainError

    try:
        action(trip, ops, now, counts)
        return True
    except DomainError as exc:
        logger.warning("Watchdog couldn't close %s: %s", trip.trip_number, exc)
        return False


def _before_pickup(trip, ops, now, counts) -> None:
    from apps.rides import services as rides

    if now - trip.requested_at > TOO_OLD_TO_REASSIGN:
        rides.cancel_trip(
            trip, user=ops, reason="Closed: the driver's app stopped responding", now=now
        )
        counts["closed"] += 1
    else:  # the driver vanished before pickup: find the rider someone else
        rides.cancel_trip(
            trip, user=trip.driver.user, reason="The driver's app stopped responding", now=now
        )
        counts["reassigned"] += 1


def _never_started(trip, ops, now, counts) -> None:
    from apps.rides import services as rides

    rides.cancel_trip(trip, user=ops, reason="Closed: the trip never started", now=now)
    counts["closed"] += 1


def _abandoned(trip, ops, now, counts) -> None:
    from apps.rides import services as rides
    from apps.support.services import open_ticket

    trip = rides.cancel_trip(
        trip,
        user=ops,
        reason="Closed: this trip stopped moving and couldn't be finished. You won't be "
        "charged; our support team will be in touch.",
        now=now,
    )
    if TripFlag.ABANDONED not in trip.flags:
        Trip.objects.filter(pk=trip.pk).update(flags=[*trip.flags, TripFlag.ABANDONED])
    open_ticket(
        user=trip.rider.user,
        category="SAFETY",
        subject=f"Abandoned trip {trip.trip_number}",
        description="The watchdog closed a trip in progress whose driver went silent. "
        "Check the rider got to their destination safely, and talk to the driver.",
        trip=trip,
        priority="HIGH",
        now=now,
    )
    counts["abandoned"] += 1
