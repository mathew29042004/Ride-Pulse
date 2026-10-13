"""The trip state machine. Every status change goes through ``assert_transition``.

::

    REQUESTED ─accept─▶ DRIVER_ASSIGNED ─arrive─▶ DRIVER_ARRIVED ─PIN─▶ IN_PROGRESS ─▶ COMPLETED
      │  ▲                 │                         │                      │
      │  └─driver cancels──┘                         │                      │
      ├─▶ NO_DRIVER_FOUND  └────────────┬────────────┴──────────────────────┘
      └───────────────────────────────▶ CANCELLED
"""

from apps.core.exceptions import InvalidStateTransition

from .models import TripStatus

S = TripStatus

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    S.REQUESTED: frozenset({S.DRIVER_ASSIGNED, S.CANCELLED, S.NO_DRIVER_FOUND}),
    # Back to REQUESTED when the driver cancels: the trip is re-dispatched to someone else.
    S.DRIVER_ASSIGNED: frozenset({S.DRIVER_ARRIVED, S.CANCELLED, S.REQUESTED}),
    S.DRIVER_ARRIVED: frozenset({S.IN_PROGRESS, S.CANCELLED}),
    # Only operations can cancel a trip in progress (e.g. after an SOS).
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
    S.NO_DRIVER_FOUND: frozenset(),
}


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise InvalidStateTransition(
            f"A trip can't go from {S(from_status).label.lower()} to {S(to_status).label.lower()}."
        )
