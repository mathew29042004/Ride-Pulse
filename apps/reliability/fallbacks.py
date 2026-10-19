"""Fallback modes: when ops open an incident on a part of the service, the app switches to a
simpler mode that still works, and switches back when the incident is resolved.

* **Payments down** → cash only (and wallet, which is our own ledger): UPI and card are refused
  for bookings and top-ups with a clear message, and the apps pre-select cash.
* **Maps down** → simple routes: no calls to the maps provider at all (no timeouts piling up);
  fares and ETAs use straight-line distance × the road factor, as they already do offline.
"""

from django.core.cache import cache

from apps.core.exceptions import BusinessRuleViolation

CASH_ONLY = "cash_only"
SIMPLE_ROUTES = "simple_routes"
_KEY = "fallback-modes"


def active() -> set[str]:
    """Fallbacks in force (cached for 30 seconds: it's read on every booking)."""
    cached = cache.get(_KEY)
    if cached is not None:
        return set(cached)
    from .models import Component, Incident, IncidentStatus

    modes = set()
    for components in Incident.objects.exclude(status=IncidentStatus.RESOLVED).values_list(
        "components", flat=True
    ):
        if Component.PAYMENTS in components:
            modes.add(CASH_ONLY)
        if Component.MAPS in components:
            modes.add(SIMPLE_ROUTES)
    cache.set(_KEY, sorted(modes), 30)
    return modes


def forget() -> None:
    """Call when an incident opens, changes or resolves."""
    cache.delete(_KEY)


def check_payment(method: str) -> None:
    from apps.payments.models import ONLINE_METHODS

    if method in ONLINE_METHODS and CASH_ONLY in active():
        raise BusinessRuleViolation(
            "Online payments are down right now. Pay in cash or from your wallet; we'll tell you "
            "when UPI and cards are back.",
            field="payment_method",
        )
