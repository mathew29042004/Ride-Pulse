"""Flight-aware airport pickups: book a pickup with your flight number and the driver comes when
you actually land, not when the timetable said.

* The pickup is set to the flight's landing time plus ``BAGGAGE_BUFFER`` (time to reach the
  pickup point with bags).
* Every 5 minutes, scheduled airport pickups re-check the flight. If the landing time moves by 5
  minutes or more, the pickup moves with it and the rider is told. Cancelled flights cancel the
  pickup at no charge.
* Flight status comes from ``status()``. The demo simulates it from the flight number and date
  (the same answer every time, so it's testable); a real feed (e.g. AviationStack or FlightAware)
  plugs in there when ``FLIGHT_STATUS_API_KEY`` is set.
"""

import hashlib
import re
from datetime import datetime, timedelta

from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

BAGGAGE_BUFFER = timedelta(minutes=30)
FLIGHT = re.compile(r"^([A-Z0-9]{2})\s?(\d{1,4})$")
# Simulated delays (minutes) and how often each happens.
_DELAYS = [0, 0, 0, 0, 0, -10, 15, 25, 40, 75, 140]


def normalise(flight: str) -> str:
    m = FLIGHT.match(flight.strip().upper())
    if not m:
        raise BusinessRuleViolation(
            "Enter the flight number, like 6E 2134 or AI 543.", field="flight_number"
        )
    return f"{m.group(1)} {m.group(2)}"


def status(flight: str, scheduled_arrival: datetime) -> dict:
    """{"state": "SCHEDULED"|"DELAYED"|"EARLY"|"LANDED"|"CANCELLED", "landing": datetime}."""
    seed = int(hashlib.sha256(f"{flight}|{scheduled_arrival:%Y-%m-%d}".encode()).hexdigest(), 16)
    if seed % 97 == 0:
        return {"state": "CANCELLED", "landing": scheduled_arrival, "delay_min": 0}
    delay = _DELAYS[seed % len(_DELAYS)]
    landing = scheduled_arrival + timedelta(minutes=delay)
    state = (
        "LANDED"
        if landing <= timezone.now()
        else "DELAYED"
        if delay > 0
        else "EARLY"
        if delay < 0
        else "SCHEDULED"
    )
    return {"state": state, "landing": landing, "delay_min": delay}


def at_airport(lat: float, lng: float) -> bool:
    from apps.geo.models import Zone

    return any(z.distance_km(lat, lng) <= z.radius_km for z in Zone.objects.filter(is_airport=True))


def pickup_for(flight: str, arrival: datetime) -> tuple[datetime, dict]:
    s = status(flight, arrival)
    return s["landing"] + BAGGAGE_BUFFER, s


def follow(*, now=None) -> dict:
    """Every 5 minutes: move airport pickups with their flights."""
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    from .models import ScheduledRide, ScheduledRideStatus

    now = now or timezone.now()
    stats = {"checked": 0, "moved": 0, "cancelled": 0}
    rides = ScheduledRide.objects.filter(
        status=ScheduledRideStatus.SCHEDULED,
        flight_number__gt="",
        flight_arrival__lte=now + timedelta(hours=12),
    ).select_related("rider__user")
    for ride in rides:
        stats["checked"] += 1
        new_pickup, s = pickup_for(ride.flight_number, ride.flight_arrival)
        if s["state"] == "CANCELLED":
            ride.status, ride.failure_reason = (
                ScheduledRideStatus.CANCELLED,
                f"Flight {ride.flight_number} was cancelled",
            )
            ride.flight_status = "CANCELLED"
            ride.save(update_fields=["status", "failure_reason", "flight_status", "updated_at"])
            notify(
                ride.rider.user,
                f"Flight {ride.flight_number} cancelled",
                "We've cancelled your airport pickup at no charge.",
                level=Level.WARNING,
                link="/ride/activity",
            )
            stats["cancelled"] += 1
            continue
        ride.flight_status = s["state"]
        if abs((new_pickup - ride.scheduled_for).total_seconds()) >= 300:
            ride.scheduled_for = new_pickup
            ride.save(update_fields=["scheduled_for", "flight_status", "updated_at"])
            when = timezone.localtime(new_pickup)
            notify(
                ride.rider.user,
                f"Flight {ride.flight_number}: pickup moved to {when:%I:%M %p}",
                f"Your flight now lands at {timezone.localtime(s['landing']):%I:%M %p}. "
                "Your driver will be there 30 minutes after, to give you time for bags.",
                link="/ride/activity",
            )
            stats["moved"] += 1
        else:
            ride.save(update_fields=["flight_status", "updated_at"])
    return stats
