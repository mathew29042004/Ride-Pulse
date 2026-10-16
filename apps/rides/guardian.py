"""Guardian mode: when something goes wrong, the rider's live location goes to the people they
trust, without them having to do anything.

Riders switch it on themselves (Account → Safety); switching it on is their consent to share
their location with their trusted contacts in an emergency.

* **Triggers**: the rider presses SOS or shakes the phone hard, a Ride Check fires (a long stop,
  far off the route, running very late, the car's signal lost) or goes unanswered, or the rider
  taps "Share my location".
* **What contacts get**: one SMS (and an in-app alert if they use Ride Pulse) with what happened,
  a map pin of the last known location, and a live link that keeps updating: from the rider's
  phone while the app is open, otherwise from the car.
* **Phone gone quiet**: if no fresh location arrives for 5 minutes, contacts get the last known
  location again with its time (every 10 minutes, at most 3 times).
* **It ends** when the rider taps "I'm safe" (contacts are told), when ops close it, or after 12
  hours. The link stops showing a location as soon as it ends.
"""

import logging
import secrets
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import conf
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.reliability.jobs import tracked

from .models import EmergencyShare, LocationSource, ShareTrigger, Trip, TripStatus
from .safety import _text

logger = logging.getLogger(__name__)

QUIET_AFTER = timedelta(minutes=5)
REMIND_EVERY = timedelta(minutes=10)
MAX_REMINDERS = 3
EXPIRES_AFTER = timedelta(hours=12)
PHONE_FRESH = timedelta(minutes=2)  # prefer the phone's own fix when it's this recent


def link(share: EmergencyShare) -> str:
    return f"{conf.app_url()}/safe/{share.token}"


def maps_pin(lat: float, lng: float) -> str:
    return f"https://maps.google.com/?q={lat:.5f},{lng:.5f}"


def _active_trip(rider) -> Trip | None:
    return (
        Trip.objects.filter(
            rider=rider,
            status__in=[
                TripStatus.DRIVER_ASSIGNED,
                TripStatus.DRIVER_ARRIVED,
                TripStatus.IN_PROGRESS,
            ],
        )
        .select_related("driver", "vehicle")
        .first()
    )


def _car_location(trip: Trip | None):
    if trip and trip.driver_id and trip.driver.current_lat is not None:
        return trip.driver.current_lat, trip.driver.current_lng, trip.driver.location_updated_at
    return None


def start(
    rider,
    trigger: str,
    *,
    trip: Trip | None = None,
    lat: float | None = None,
    lng: float | None = None,
    detail: str = "",
    force: bool = False,
    now: datetime | None = None,
) -> EmergencyShare | None:
    """Start sharing (or add the trigger to the share already running). Only for riders who
    switched Guardian mode on, unless the rider shares by hand (``force``)."""
    now = now or timezone.now()
    if not (rider.guardian_mode or force):
        return None
    contacts = list(rider.contacts.all())
    trip = trip or _active_trip(rider)
    source = LocationSource.PHONE if lat is not None else LocationSource.CAR  # given = phone's
    if lat is None:
        car = _car_location(trip)
        if car:
            lat, lng = car[0], car[1]
    share = EmergencyShare.objects.filter(rider=rider, ended_at__isnull=True).first()
    if share is not None:
        if trigger not in share.triggers:
            share.triggers = [*share.triggers, trigger]
            share.save(update_fields=["triggers"])
        if lat is not None:
            record(share, lat=lat, lng=lng, source=source, now=now)
        return share
    try:
        with transaction.atomic():
            share = EmergencyShare.objects.create(
                rider=rider,
                trip=trip,
                triggers=[trigger],
                detail=detail[:200],
                token=secrets.token_urlsafe(18)[:32],
                started_at=now,
                last_lat=lat,
                last_lng=lng,
                last_source=source if lat is not None else "",
                last_at=now if lat is not None else None,
            )
    except IntegrityError:  # started by a parallel trigger a moment ago
        return EmergencyShare.objects.filter(rider=rider, ended_at__isnull=True).first()
    what = ShareTrigger(trigger).label.lower()
    car = ""
    if trip and trip.vehicle_id:
        car = f" in {trip.vehicle.registration_number}"
        if trip.driver_id:
            car += f" (driver {trip.driver.name})"
    where = f" Last seen: {maps_pin(lat, lng)}" if lat is not None else ""
    share.contacts_alerted = _text(
        contacts,
        f"Ride Pulse alert: {rider.name} may need help ({what}){car}.{where} "
        f"Live location: {link(share)}",
    )
    share.save(update_fields=["contacts_alerted"])
    notify(
        rider.user,
        "Your location is being shared",
        f"{share.contacts_alerted} trusted contact{'s' if share.contacts_alerted != 1 else ''} "
        'can see where you are. Tap "I\'m safe" when you are.',
        level=Level.WARNING,
        link="/ride",
    )
    from apps.realtime import broadcast

    broadcast.ops_event(
        "guardian", {"share_id": share.pk, "rider_id": rider.pk, "trigger": trigger}
    )
    return share


def record(share: EmergencyShare, *, lat: float, lng: float, source: str, now=None) -> None:
    """A new location for an open share (the phone's own fix wins over the car's)."""
    now = now or timezone.now()
    if share.ended_at is not None:
        return
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise BusinessRuleViolation("That isn't a valid location.")
    if (
        source == LocationSource.CAR
        and share.last_source == LocationSource.PHONE
        and share.last_at
        and now - share.last_at < PHONE_FRESH
    ):
        return
    EmergencyShare.objects.filter(pk=share.pk).update(
        last_lat=lat, last_lng=lng, last_source=source, last_at=now
    )
    share.last_lat, share.last_lng, share.last_source, share.last_at = lat, lng, source, now


def phone_location(rider, *, lat: float, lng: float, now=None) -> EmergencyShare | None:
    share = EmergencyShare.objects.filter(rider=rider, ended_at__isnull=True).first()
    if share:
        record(share, lat=lat, lng=lng, source=LocationSource.PHONE, now=now)
    return share


def end(share: EmergencyShare, *, user, now=None) -> EmergencyShare:
    now = now or timezone.now()
    is_rider = share.rider.user_id == user.pk
    if not (is_rider or getattr(user, "is_staff_member", False) or user.is_staff):
        raise ActionNotPermitted("Only the rider or the safety team can end this.")
    if share.ended_at:
        return share
    share.ended_at, share.ended_by = now, "RIDER" if is_rider else "OPS"
    share.save(update_fields=["ended_at", "ended_by"])
    _text(
        share.rider.contacts.all(),
        f"{share.rider.name} says they're safe now. Location sharing has stopped. Ride Pulse"
        if is_rider
        else f"Our safety team has closed {share.rider.name}'s alert. Ride Pulse",
    )
    return share


def rider_ok(rider, *, now=None) -> None:
    """The rider answered "I'm OK" to a Ride Check: an alert raised only by Ride Checks ends,
    and contacts are told. (An SOS stays open until the rider says they're safe.)"""
    share = EmergencyShare.objects.filter(rider=rider, ended_at__isnull=True).first()
    if share and set(share.triggers) <= {ShareTrigger.RIDE_CHECK}:
        end(share, user=rider.user, now=now)


@tracked("guardian", every=timedelta(minutes=1))
def sweep(*, now: datetime | None = None) -> dict:
    """Every minute: follow the car, remind contacts if the phone went quiet, expire."""
    now = now or timezone.now()
    reminded = expired = 0
    for share in EmergencyShare.objects.filter(ended_at__isnull=True).select_related(
        "rider__user", "trip__driver"
    ):
        if now - share.started_at > EXPIRES_AFTER:
            share.ended_at, share.ended_by = now, "EXPIRED"
            share.save(update_fields=["ended_at", "ended_by"])
            expired += 1
            continue
        car = _car_location(share.trip) if share.trip and share.trip.is_active else None
        if car and car[2] and (share.last_at is None or car[2] > share.last_at):
            record(share, lat=car[0], lng=car[1], source=LocationSource.CAR, now=car[2])
        quiet = share.last_at is None or now - share.last_at > QUIET_AFTER
        due = share.last_reminder_at is None or now - share.last_reminder_at >= REMIND_EVERY
        if quiet and due and share.reminders_sent < MAX_REMINDERS and share.last_lat is not None:
            when = timezone.localtime(share.last_at).strftime("%I:%M %p")
            _text(
                share.rider.contacts.all(),
                f"Ride Pulse: we haven't had a new location from {share.rider.name} since {when}. "
                f"Last known: {maps_pin(share.last_lat, share.last_lng)} · {link(share)}",
            )
            EmergencyShare.objects.filter(pk=share.pk).update(
                reminders_sent=share.reminders_sent + 1, last_reminder_at=now
            )
            reminded += 1
    return {"reminded": reminded, "expired": expired}


def public_view(token: str) -> dict | None:
    share = (
        EmergencyShare.objects.filter(token=token)
        .select_related("rider__user", "trip__vehicle", "trip__driver__user")
        .first()
    )
    if share is None:
        return None
    trip = share.trip
    active = share.ended_at is None
    return {
        "name": share.rider.name,
        "active": active,
        "triggers": [ShareTrigger(t).label for t in share.triggers],
        "started_at": share.started_at.isoformat(),
        "ended_at": share.ended_at.isoformat() if share.ended_at else None,
        "ended_by": share.ended_by,
        # The location is only shown while the alert is open.
        "location": {
            "lat": share.last_lat,
            "lng": share.last_lng,
            "source": share.last_source,
            "at": share.last_at.isoformat() if share.last_at else None,
        }
        if active and share.last_lat is not None
        else None,
        "trip": {
            "number": trip.trip_number,
            "status": trip.get_status_display(),
            "vehicle": str(trip.vehicle) if trip.vehicle_id else None,
            "registration": trip.vehicle.registration_number if trip.vehicle_id else None,
            "driver": trip.driver.name if trip.driver_id else None,
            "pickup": trip.pickup_address,
            "dropoff": trip.dropoff_address,
        }
        if trip and active
        else None,
        "phone": share.rider.user.phone if active else None,
    }
