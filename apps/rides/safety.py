"""Safety+: Ride Check, Night Safe mode and trusted contacts.

* **Ride Check.** Every minute the server looks at trips in progress and raises an "Is everything
  OK?" check when the car has stopped for a while, is far from the route, is running very late, or
  its location went silent. The rider answers in the app; "Get help", or no answer within a few
  minutes, opens a safety incident (like SOS) and alerts the rider's trusted contacts. On a long
  stop or lost signal the driver is asked too.
* **Night Safe mode** (10 pm – 6 am, and every "woman driver" ride; riders can turn it off):
  stricter Ride Check limits, the trip is shared with trusted contacts, the driver can't end the
  trip far from the drop unless the rider confirms, and "I'm home safe" tells contacts after.
* **Trusted contacts** (up to 3) get the live "follow my ride" link by SMS: every ride, night
  rides only, or only when the rider shares.
"""

import itertools
import logging
import math
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts import sms
from apps.core import conf
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.geo.distance import haversine_km
from apps.geo.google import decode_polyline
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import (
    RideCheck,
    RideCheckKind,
    RideCheckStatus,
    RidePreference,
    Trip,
    TripFlag,
    TripStatus,
)

logger = logging.getLogger(__name__)

MAX_CONTACTS = 3
STOPPED_RADIUS_KM = 0.15
DROP_RADIUS_KM = 0.5
HOME_SAFE_WINDOW = timedelta(hours=3)
# Simulated riders from the seeder answer Ride Checks by themselves.
BOT_RIDER_DOMAIN = "@example.com"


# --- Night Safe mode ------------------------------------------------------------------------


def is_night(now: datetime) -> bool:
    start, end = conf.night_safe_hours()
    hour = timezone.localtime(now).hour
    return hour >= start or hour < end if start > end else start <= hour < end


def night_safe_for(trip: Trip, now: datetime) -> bool:
    """Decided when the trip starts: at night, or on a "woman driver" ride, unless turned off."""
    if not trip.rider.night_safety or trip.service != "RIDE":
        return False
    return is_night(now) or RidePreference.WOMAN_DRIVER in (trip.preferences or [])


def assert_can_complete(trip: Trip, driver, *, now: datetime) -> None:
    """Night Safe rides end at the drop point, unless the rider confirmed an earlier stop."""
    if not trip.night_safe or trip.early_drop_confirmed or driver.current_lat is None:
        return
    away = haversine_km(driver.current_lat, driver.current_lng, trip.dropoff_lat, trip.dropoff_lng)
    if away > DROP_RADIUS_KM:
        raise BusinessRuleViolation(
            f"This is a Night Safe ride and you're {away:.1f} km from the drop. Drive to the drop "
            "point, or ask the rider to confirm the early stop in their app."
        )


@transaction.atomic
def confirm_early_drop(trip: Trip, *, user) -> Trip:
    trip = (
        Trip.objects.select_for_update(of=("self",)).select_related("driver__user").get(pk=trip.pk)
    )
    _require_rider(trip, user)
    if trip.status != TripStatus.IN_PROGRESS:
        raise InvalidStateTransition("You can only confirm a drop during the trip.")
    trip.early_drop_confirmed = True
    trip.save(update_fields=["early_drop_confirmed", "updated_at"])
    notify(
        trip.driver.user,
        "Rider confirmed the drop here",
        "You can end the trip at this point.",
        level=Level.SUCCESS,
        link="/drive",
    )
    return trip


# --- Trusted contacts ------------------------------------------------------------------------


def _share_link(trip: Trip) -> str:
    if not trip.share_token:
        trip.share_token = secrets.token_urlsafe(18)
        trip.save(update_fields=["share_token", "updated_at"])
    return f"{conf.app_url()}/track/{trip.share_token}"


def contacts_for(trip: Trip):
    from apps.riders.models import ShareMode

    modes = [ShareMode.ALWAYS, *([ShareMode.NIGHT] if trip.night_safe else [])]
    return trip.rider.contacts.filter(share_mode__in=modes)


def _text(contacts, message: str) -> int:
    from apps.accounts.models import User

    sent = 0
    for contact in contacts:
        try:
            sms.send_text(contact.phone, message)
            sent += 1
        except sms.SMSError as exc:
            logger.warning("Couldn't text trusted contact %s: %s", contact.pk, exc)
        # Contacts who also use Ride Pulse get it in the app too.
        user = User.objects.filter(phone=contact.phone, is_active=True).first()
        if user:
            notify(user, "Ride Pulse safety", message, level=Level.INFO)
    return sent


def share_with_contacts(trip_id: int, *, now: datetime | None = None) -> int:
    """Text the live trip link to the contacts who asked for this kind of ride (once)."""
    now = now or timezone.now()
    trip = Trip.objects.select_related("rider__user", "ride_type", "vehicle").get(pk=trip_id)
    if trip.contacts_notified_at or trip.status != TripStatus.IN_PROGRESS:
        return 0
    from apps.trust.models import ConsentPurpose
    from apps.trust.privacy import has_consent

    if not has_consent(trip.rider.user, ConsentPurpose.CONTACT_SHARING):
        return 0  # the rider switched sharing off in their privacy settings
    contacts = list(contacts_for(trip))
    if not contacts:
        return 0
    car = f" ({trip.vehicle.registration_number})" if trip.vehicle else ""
    sent = _text(
        contacts,
        f"{trip.rider.name} started a {trip.ride_type.name} ride{car} on Ride Pulse. "
        f"Follow it live: {_share_link(trip)}",
    )
    Trip.objects.filter(pk=trip.pk).update(contacts_notified_at=now)
    return sent


@transaction.atomic
def home_safe(trip: Trip, *, user, now: datetime | None = None) -> Trip:
    """ "I'm home safe": tells the contacts who followed the ride."""
    now = now or timezone.now()
    trip = Trip.objects.select_for_update().select_related("rider__user").get(pk=trip.pk)
    _require_rider(trip, user)
    if trip.status != TripStatus.COMPLETED:
        raise InvalidStateTransition("You can check in after the ride ends.")
    if trip.home_safe_at:
        return trip
    if now - trip.completed_at > HOME_SAFE_WINDOW:
        raise BusinessRuleViolation("Check-ins are open for 3 hours after the ride.")
    contacts = list(contacts_for(trip))
    _text(contacts, f"{trip.rider.name} reached safely. Thanks for keeping an eye out. Ride Pulse")
    trip.home_safe_at = now
    trip.save(update_fields=["home_safe_at", "updated_at"])
    return trip


# --- Ride Check -------------------------------------------------------------------------------


def _route_points(trip: Trip) -> list[tuple[float, float]]:
    if trip.route_polyline:
        try:
            points = decode_polyline(trip.route_polyline)
            if len(points) >= 2:
                return points
        except (ValueError, IndexError):
            pass
    points = [(trip.pickup_lat, trip.pickup_lng)]
    if trip.stop_lat is not None:
        points.append((trip.stop_lat, trip.stop_lng))
    points += [(stop["lat"], stop["lng"]) for stop in trip.extra_stops or []]
    return [*points, (trip.dropoff_lat, trip.dropoff_lng)]


def distance_to_route_km(points: list[tuple[float, float]], lat: float, lng: float) -> float:
    """Shortest distance from a point to a polyline (flat-earth maths is fine at city scale)."""
    ky = 111.32
    kx = 111.32 * math.cos(math.radians(lat))
    best = math.inf
    for (alat, alng), (blat, blng) in itertools.pairwise(points):
        ax, ay = (alng - lng) * kx, (alat - lat) * ky
        bx, by = (blng - lng) * kx, (blat - lat) * ky
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _detect(trip: Trip, now: datetime) -> list[str]:
    from apps.drivers.models import LocationPing

    rules = conf.ride_check_rules(night=trip.night_safe)
    stop = timedelta(minutes=rules["stop_minutes"])
    driver = trip.driver
    found = []
    if now - trip.started_at >= stop:
        seen = driver.location_updated_at
        if seen is None or now - seen > stop:
            found.append(RideCheckKind.SIGNAL_LOST)
        else:
            pings = list(
                LocationPing.objects.filter(trip=trip, recorded_at__gte=now - stop).values_list(
                    "lat", "lng", "recorded_at"
                )
            )
            spans_window = pings and min(p[2] for p in pings) <= now - stop * 0.6
            if (
                len(pings) >= 2
                and spans_window
                and all(
                    haversine_km(lat, lng, driver.current_lat, driver.current_lng)
                    <= STOPPED_RADIUS_KM
                    for lat, lng, _ in pings
                )
            ):
                found.append(RideCheckKind.LONG_STOP)
    if driver.current_lat is not None and (
        distance_to_route_km(_route_points(trip), driver.current_lat, driver.current_lng)
        > rules["off_route_km"]
    ):
        found.append(RideCheckKind.OFF_ROUTE)
    expected = float(trip.estimated_duration_min) * (1.3 if trip.night_safe else 1.5)
    expected += 10 if trip.night_safe else 15
    if (now - trip.started_at).total_seconds() / 60 > expected:
        found.append(RideCheckKind.RUNNING_LATE)
    return found


def _raise(trip: Trip, kind: str, now: datetime) -> RideCheck | None:
    from apps.realtime import broadcast

    check, created = RideCheck.objects.get_or_create(
        trip=trip,
        kind=kind,
        defaults={
            "lat": trip.driver.current_lat,
            "lng": trip.driver.current_lng,
            "created_at": now,
        },
    )
    if not created:
        return None
    label = RideCheckKind(kind).label
    minutes = conf.ride_check_rules(night=trip.night_safe)["answer_minutes"]
    notify(
        trip.rider.user,
        "Is everything OK?",
        f"{label}. Tap to answer. If we don't hear back in {minutes} minutes, "
        "our safety team will check on you.",
        level=Level.WARNING,
        link=f"/ride/trips/{trip.pk}/",
    )
    if kind in (RideCheckKind.LONG_STOP, RideCheckKind.SIGNAL_LOST):
        notify(
            trip.driver.user,
            "Are you OK?",
            f"{label}. Let us know in the app that everything is fine.",
            level=Level.WARNING,
            link="/drive",
        )
    broadcast.trip_event(trip.pk, "ride_check", {"id": check.pk, "kind": kind})
    from . import guardian
    from .models import ShareTrigger

    # Guardian mode: contacts see the location at the first sign of trouble, not only later.
    guardian.start(trip.rider, ShareTrigger.RIDE_CHECK, trip=trip, detail=label, now=now)
    return check


def _escalate(check: RideCheck, *, status: str, note: str, now: datetime) -> RideCheck:
    from apps.support.services import raise_sos

    trip = check.trip
    incident = raise_sos(
        trip=trip,
        user=trip.rider.user,
        lat=check.lat,
        lng=check.lng,
        note=f"Automatic Ride Check ({RideCheckKind(check.kind).label}): {note}",
        now=now,
    )
    check.status = status
    check.incident = incident
    check.answered_at = check.answered_at or (now if status == RideCheckStatus.HELP else None)
    check.save(update_fields=["status", "incident", "answered_at"])
    if TripFlag.RIDE_CHECK not in trip.flags:
        Trip.objects.filter(pk=trip.pk).update(flags=[*trip.flags, TripFlag.RIDE_CHECK])
    # In an emergency every trusted contact hears about it, whatever their sharing setting.
    _text(
        trip.rider.contacts.all(),
        f"Ride Pulse safety alert: {trip.rider.name}'s ride needs a check "
        f"({RideCheckKind(check.kind).label.lower()}). Our safety team is on it. "
        f"Live trip: {_share_link(trip)}",
    )
    return check


def run_ride_checks(now: datetime | None = None) -> dict:
    """Raise new checks on trips in progress, then escalate the ones nobody answered."""
    now = now or timezone.now()
    raised = escalated = closed = 0
    trips = Trip.objects.filter(
        status=TripStatus.IN_PROGRESS, started_at__isnull=False, service="RIDE"
    )
    for trip in trips.select_related("driver", "driver__user", "rider__user").prefetch_related(
        "ride_checks"
    ):
        known = {c.kind for c in trip.ride_checks.all()}
        for kind in _detect(trip, now):
            if kind not in known:
                with transaction.atomic():
                    raised += bool(_raise(trip, kind, now))

    for check in RideCheck.objects.filter(status=RideCheckStatus.OPEN).select_related(
        "trip__rider__user", "trip__driver"
    ):
        minutes = conf.ride_check_rules(night=check.trip.night_safe)["answer_minutes"]
        if now - check.created_at < timedelta(minutes=minutes):
            continue
        with transaction.atomic():
            if check.trip.status == TripStatus.IN_PROGRESS:
                _escalate(check, status=RideCheckStatus.ESCALATED, note="no answer", now=now)
                escalated += 1
            else:
                check.status = RideCheckStatus.CLOSED
                check.save(update_fields=["status"])
                closed += 1
    return {"raised": raised, "escalated": escalated, "closed": closed}


@transaction.atomic
def answer(check: RideCheck, *, user, ok: bool, now: datetime | None = None) -> RideCheck:
    now = now or timezone.now()
    check = (
        RideCheck.objects.select_for_update(of=("self",))
        .select_related("trip__rider__user", "trip__driver__user")
        .get(pk=check.pk)
    )
    trip = check.trip
    is_rider = trip.rider.user_id == user.pk
    is_driver = trip.driver_id is not None and trip.driver.user_id == user.pk
    if not (is_rider or is_driver):
        raise ActionNotPermitted("Only the rider or driver can answer a Ride Check.")
    if is_driver:
        check.driver_ok = ok
        check.save(update_fields=["driver_ok"])
        if not ok and check.incident_id is None:
            _escalate(check, status=RideCheckStatus.HELP, note="the driver asked for help", now=now)
        return check
    if check.status != RideCheckStatus.OPEN and (ok or check.incident_id):
        return check  # already handled; answering twice is harmless
    if ok:
        check.status = RideCheckStatus.OK
        check.answered_at = now
        check.save(update_fields=["status", "answered_at"])
        from . import guardian

        guardian.rider_ok(trip.rider, now=now)
        return check
    return _escalate(check, status=RideCheckStatus.HELP, note="the rider asked for help", now=now)


def answer_for_bots(now: datetime | None = None) -> int:
    """The simulator's riders and drivers are fine: answer their checks so ops isn't paged."""
    from apps.riders.models import RiderProfile

    from . import guardian

    open_checks = RideCheck.objects.filter(
        status=RideCheckStatus.OPEN, trip__rider__user__email__endswith=BOT_RIDER_DOMAIN
    )
    rider_ids = set(open_checks.values_list("trip__rider_id", flat=True))
    answered = open_checks.update(status=RideCheckStatus.OK, answered_at=now or timezone.now())
    for rider in RiderProfile.objects.filter(pk__in=rider_ids).select_related("user"):
        guardian.rider_ok(rider, now=now)
    return answered


def _require_rider(trip: Trip, user) -> None:
    if trip.rider.user_id != user.pk:
        raise ActionNotPermitted("Only the rider can do this.")


def belt_reminder(trip) -> None:
    """Seatbelt (cars) or helmet (bikes) reminder when the ride starts."""
    from apps.notifications.services import notify

    if trip.ride_type.served_by.code == "BIKE":
        title, body = (
            "Wear your helmet",
            "Ask your captain for the passenger helmet and strap it on.",
        )
    elif trip.ride_type.served_by.code == "AUTO":
        return
    else:
        title, body = "Buckle up", "Please wear your seatbelt, including in the back seat."
    notify(trip.rider.user, title, body, link=f"/ride/trips/{trip.pk}/")
