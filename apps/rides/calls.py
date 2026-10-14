"""Masked calling between rider and driver, so neither ever sees the other's number.

With Exotel configured (EXOTEL_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_CALLER_ID, and
EXOTEL_SUBDOMAIN, e.g. api.exotel.com) a call uses Exotel's click-to-call: Exotel rings the
caller from a Ride Pulse virtual number and, when they pick up, connects them to the other
party, who also sees only the virtual number. Without it, calls run in demo mode: nothing is
dialled and the app explains what would happen.

Calls are allowed from when a driver is assigned until 30 minutes after the trip ends (for lost
items), are rate limited, and are logged on the trip timeline for safety reviews.
"""

import base64
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError

from .models import ACTIVE_STATUSES, Trip, TripStatus

CALL_WINDOW_AFTER_TRIP = timedelta(minutes=30)
MAX_CALLS_PER_TRIP = 10
TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class CallResult:
    mode: str  # "exotel" or "demo"
    message: str
    reference: str = ""


def enabled() -> bool:
    return all(
        getattr(settings, name, "")
        for name in ("EXOTEL_SID", "EXOTEL_API_KEY", "EXOTEL_API_TOKEN", "EXOTEL_CALLER_ID")
    )


def _exotel_connect(caller_phone: str, callee_phone: str) -> str:
    sid = settings.EXOTEL_SID
    auth = base64.b64encode(f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}".encode())
    request = urllib.request.Request(
        f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{sid}/Calls/connect.json",
        data=urllib.parse.urlencode(
            {
                "From": f"0{caller_phone}",
                "To": f"0{callee_phone}",
                "CallerId": settings.EXOTEL_CALLER_ID,
                "TimeLimit": "900",
            }
        ).encode(),
        headers={"Authorization": f"Basic {auth.decode()}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            import json

            return json.loads(response.read()).get("Call", {}).get("Sid", "")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BusinessRuleViolation("We couldn't place the call. Try again shortly.") from exc


def call_other_party(trip: Trip, *, user) -> CallResult:
    from .services import record_event

    if user.is_rider and trip.rider.user_id == user.pk:
        caller, callee, role = user, (trip.driver.user if trip.driver_id else None), "driver"
    elif user.is_driver and trip.driver_id and trip.driver.user_id == user.pk:
        caller, callee, role = user, trip.rider.user, "rider"
    else:
        raise ActionNotPermitted("Only the rider and driver can call each other.")
    if callee is None:
        raise BusinessRuleViolation("No driver yet: calling opens once one is assigned.")
    ended = trip.completed_at or trip.cancelled_at
    open_now = trip.status in ACTIVE_STATUSES and trip.status != TripStatus.REQUESTED
    from .lost_items import calls_open

    recently_ended = ended and timezone.now() - ended < CALL_WINDOW_AFTER_TRIP
    if not open_now and not recently_ended and not calls_open(trip):
        raise BusinessRuleViolation("Calling is closed for this trip. Contact support for help.")
    if trip.events.filter(kind="CALL", actor=user).count() >= MAX_CALLS_PER_TRIP:
        raise ConflictError("Call limit reached for this trip. Use chat or contact support.")
    if not (caller.phone and callee.phone):
        raise BusinessRuleViolation("A phone number is missing on one of the accounts.")

    if enabled():
        reference = _exotel_connect(caller.phone, callee.phone)
        result = CallResult(
            "exotel",
            f"Ride Pulse is calling you now. Pick up to be connected to your {role}; "
            "both numbers stay private.",
            reference,
        )
    else:
        result = CallResult(
            "demo",
            f"Demo mode: in the live app Ride Pulse would ring your phone and connect you to "
            f"your {role} through a private number. No call was placed.",
        )
    record_event(
        trip,
        "CALL",
        actor=user,
        message=f"Masked call to the {role}",
        data={"mode": result.mode, "reference": result.reference},
    )
    return result
