"""WebSocket endpoints.

* ``/ws/trips/<id>/``: the rider, the driver and operations watch one trip (status, driver
  position, ETA).
* ``/ws/driver/``: a driver receives trip offers and streams GPS positions.
* ``/ws/ops/``: the live operations map (every status change, driver position and SOS).
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder

from apps.accounts.roles import Cap

from . import broadcast, relay

FORBIDDEN = 4403


class BroadcastConsumer(AsyncJsonWebsocketConsumer):
    groups_joined: list[str]

    @classmethod
    async def encode_json(cls, content):
        # Payloads carry Decimal amounts and datetimes.
        return json.dumps(content, cls=DjangoJSONEncoder)

    async def join(self, group: str) -> None:
        self.groups_joined = [*getattr(self, "groups_joined", []), group]
        await self.channel_layer.group_add(group, self.channel_name)
        await relay.ensure_listener()

    async def disconnect(self, code):
        for group in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def broadcast_message(self, message):
        await self.send_json({"event": message["event"], "data": message["data"]})


@database_sync_to_async
def _trip_snapshot(user, trip_id: int):
    from apps.rides.models import Trip
    from apps.rides.services import can_view_trip, trip_payload

    trip = (
        Trip.objects.select_related("driver__user", "vehicle", "ride_type", "rider")
        .filter(pk=trip_id)
        .first()
    )
    if trip is None or not can_view_trip(user, trip):
        return None
    return trip_payload(trip)


class TripConsumer(BroadcastConsumer):
    async def connect(self):
        user = self.scope.get("user")
        trip_id = int(self.scope["url_route"]["kwargs"]["trip_id"])
        snapshot = await _trip_snapshot(user, trip_id) if user and user.is_authenticated else None
        if snapshot is None:
            await self.close(code=FORBIDDEN)
            return
        await self.join(broadcast.trip_group(trip_id))
        await self.accept()
        await self.send_json({"event": "snapshot", "data": snapshot})


@database_sync_to_async
def _driver_profile(user):
    return getattr(user, "driver_profile", None) if user.is_driver else None


@database_sync_to_async
def _update_location(driver, content: dict) -> None:
    from apps.drivers.services import update_location

    update_location(
        driver,
        lat=float(content["lat"]),
        lng=float(content["lng"]),
        speed_kmh=content.get("speed"),
        heading=content.get("heading"),
    )


class DriverConsumer(BroadcastConsumer):
    async def connect(self):
        user = self.scope.get("user")
        driver = await _driver_profile(user) if user and user.is_authenticated else None
        if driver is None:
            await self.close(code=FORBIDDEN)
            return
        self.driver = driver
        await self.join(broadcast.driver_group(driver.pk))
        await self.accept()

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "location":
            try:
                await _update_location(self.driver, content)
            except (KeyError, TypeError, ValueError):
                await self.send_json({"event": "error", "data": {"message": "Invalid location."}})
        elif content.get("type") == "ping":
            await self.send_json({"event": "pong", "data": {}})


class OpsConsumer(BroadcastConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not (user and user.is_authenticated and user.has_capability(Cap.TRIPS_VIEW)):
            await self.close(code=FORBIDDEN)
            return
        await self.join(broadcast.OPS_GROUP)
        await self.accept()


class ChatConsumer(BroadcastConsumer):
    """``/ws/chat/``: a staff member's own team-chat messages, live."""

    async def connect(self):
        user = self.scope.get("user")
        if not (user and user.is_authenticated and user.is_staff_member):
            await self.close(code=FORBIDDEN)
            return
        await self.join(broadcast.user_group(user.pk))
        await self.accept()
