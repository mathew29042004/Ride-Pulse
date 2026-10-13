"""Push events to WebSocket subscribers through the Channels layer.

Messages are sent only after the database transaction commits, so a client never hears about
a state it can't then read. Failures are logged and swallowed: real-time delivery is
best-effort, and every page can fall back to polling.

Without Redis, messages travel through PostgreSQL LISTEN/NOTIFY (see ``relay``), so events from
the simulator or a worker process still reach the web process's sockets.
"""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from . import relay

logger = logging.getLogger(__name__)
_muted: ContextVar[bool] = ContextVar("broadcast_muted", default=False)

OPS_GROUP = "ops"


def trip_group(trip_id: int) -> str:
    return f"trip.{trip_id}"


def driver_group(driver_id: int) -> str:
    return f"driver.{driver_id}"


@contextmanager
def muted():
    """Silence broadcasts, e.g. while bulk-generating historical demo data."""
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)


def _send(group: str, event: str, data: dict) -> None:
    if _muted.get():
        return
    use_relay = relay.enabled()
    layer = None if use_relay else get_channel_layer()
    if layer is None and not use_relay:
        return
    message = {
        "type": "broadcast.message",
        "event": event,
        "data": json.loads(json.dumps(data, cls=DjangoJSONEncoder)),
    }

    def deliver() -> None:
        try:
            if use_relay:
                relay.publish(group, message)
            else:
                async_to_sync(layer.group_send)(group, message)
        except Exception:  # pragma: no cover - depends on the channel layer backend
            logger.warning("Could not broadcast %s to %s", event, group, exc_info=True)

    transaction.on_commit(deliver)


def trip_event(trip_id: int, event: str, data: dict) -> None:
    _send(trip_group(trip_id), event, data)


def driver_event(driver_id: int, event: str, data: dict) -> None:
    _send(driver_group(driver_id), event, data)


def ops_event(event: str, data: dict) -> None:
    _send(OPS_GROUP, event, data)
