"""Cross-process WebSocket fan-out over PostgreSQL LISTEN/NOTIFY.

Channels' in-memory layer only reaches sockets in the same process, so without Redis an event
raised by another process (the bot simulator, a Celery worker) never reaches the browser. When
``REALTIME_RELAY`` is ``"postgres"`` every broadcast is published with ``pg_notify`` instead, and
each ASGI process LISTENs and hands what it hears to its local channel layer. PostgreSQL delivers
notifications in commit order and only after the sending transaction commits.

With Redis configured (``REALTIME_RELAY = "layer"``) the Redis channel layer does this natively
and the relay stays idle.
"""

import asyncio
import contextlib
import json
import logging

import psycopg
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import connection
from psycopg.conninfo import make_conninfo

logger = logging.getLogger(__name__)

CHANNEL = "ridepulse_events"
# NOTIFY payloads must stay under 8000 bytes.
MAX_PAYLOAD = 7_900

_listener: asyncio.Task | None = None
_ready: asyncio.Event | None = None


def enabled() -> bool:
    return getattr(settings, "REALTIME_RELAY", "layer") == "postgres"


def publish(group: str, message: dict) -> None:
    """Send one channel-layer message to every process listening (call from sync code)."""
    payload = json.dumps({"group": group, "message": message}, separators=(",", ":"))
    if len(payload) > MAX_PAYLOAD:
        # Too big for NOTIFY: send a stub. Clients refetch the record when they get an event.
        data = message.get("data") or {}
        stub = {k: data[k] for k in ("id", "trip_id", "status") if k in data}
        payload = json.dumps(
            {"group": group, "message": {**message, "data": {**stub, "partial": True}}},
            separators=(",", ":"),
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_notify(%s, %s)", [CHANNEL, payload])


def _conninfo() -> str:
    db = settings.DATABASES["default"]
    return make_conninfo(
        dbname=db["NAME"],
        user=db.get("USER") or None,
        password=db.get("PASSWORD") or None,
        host=db.get("HOST") or None,
        port=str(db["PORT"]) if db.get("PORT") else None,
    )


async def _listen(ready: asyncio.Event) -> None:
    layer = get_channel_layer()
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(_conninfo(), autocommit=True) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                ready.set()
                async for notify in conn.notifies():
                    try:
                        item = json.loads(notify.payload)
                        await layer.group_send(item["group"], item["message"])
                    except (ValueError, KeyError, TypeError):
                        logger.warning("Ignoring malformed relay payload")
        except asyncio.CancelledError:
            raise
        except Exception:
            # The database restarted or the connection dropped: keep the socket clients alive and
            # reconnect. Pages poll as well, so a short gap only costs latency.
            logger.warning("Realtime relay lost its database connection; retrying", exc_info=True)
            await asyncio.sleep(2)


async def ensure_listener(timeout: float = 3.0) -> None:
    """Start this process's listener (once) and wait until it is subscribed."""
    global _listener, _ready
    if not enabled():
        return
    if _listener is None or _listener.done():
        _ready = asyncio.Event()
        _listener = asyncio.create_task(_listen(_ready), name="realtime-relay")
    try:
        await asyncio.wait_for(_ready.wait(), timeout)
    except TimeoutError:
        logger.warning("Realtime relay is not connected yet; events may arrive late")


async def stop() -> None:
    global _listener, _ready
    if _listener is not None:
        _listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener
    _listener = _ready = None
