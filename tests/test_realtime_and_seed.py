import asyncio

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.payments.services import verify_ledger
from apps.realtime import broadcast
from apps.realtime.routing import websocket_urlpatterns
from apps.rides.models import Trip, TripStatus

from .conftest import T_NAGAR, make_rider
from .integration.helpers import book

application = URLRouter(websocket_urlpatterns)


def connect(path: str, user):
    communicator = WebsocketCommunicator(application, path)
    communicator.scope["user"] = user
    return communicator


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_trip_socket_sends_snapshot_to_the_rider_and_rejects_strangers(
    mini, make_driver, now
):
    rider = await database_sync_to_async(make_rider)()
    await database_sync_to_async(make_driver)(now=now)
    trip = await database_sync_to_async(book)(rider, mini, now=now)
    rider_user = await database_sync_to_async(lambda: rider.user)()

    communicator = connect(f"/ws/trips/{trip.pk}/", rider_user)
    connected, _ = await communicator.connect()
    assert connected
    snapshot = await communicator.receive_json_from()
    assert snapshot["event"] == "snapshot" and snapshot["data"]["status"] == TripStatus.REQUESTED
    assert "otp" not in snapshot["data"]  # the PIN is never broadcast

    await get_channel_layer().group_send(
        broadcast.trip_group(trip.pk),
        {"type": "broadcast.message", "event": "status", "data": {"status": "DRIVER_ASSIGNED"}},
    )
    pushed = await communicator.receive_json_from()
    assert pushed == {"event": "status", "data": {"status": "DRIVER_ASSIGNED"}}
    await communicator.disconnect()

    stranger = await database_sync_to_async(make_rider)()
    stranger_user = await database_sync_to_async(lambda: stranger.user)()
    blocked = connect(f"/ws/trips/{trip.pk}/", stranger_user)
    connected, code = await blocked.connect()
    assert not connected and code == 4403


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_driver_socket_accepts_gps_updates(make_driver, now):
    driver = await database_sync_to_async(make_driver)(now=now)
    user = await database_sync_to_async(lambda: driver.user)()
    communicator = connect("/ws/driver/", user)
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to(
        {"type": "location", "lat": T_NAGAR[0], "lng": T_NAGAR[1] + 0.01}
    )
    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from())["event"] == "pong"
    await communicator.disconnect()
    await database_sync_to_async(driver.refresh_from_db)()
    assert driver.current_lng == pytest.approx(T_NAGAR[1] + 0.01)


@pytest.mark.django_db
def test_demo_seed_builds_a_consistent_history():
    from apps.simulation.seed import Seeder

    stats = Seeder(days=2, trips_per_day=15, riders=12, seed=7, log=lambda *_: None).run()
    assert stats["completed"] > 5
    assert stats["ledger_balanced"] == 1 and verify_ledger()["balanced"]
    assert not Trip.objects.filter(
        status__in=["REQUESTED", "DRIVER_ASSIGNED", "IN_PROGRESS"]
    ).exists()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_postgres_relay_reaches_sockets_from_another_process(settings):
    # Without Redis, events from the simulator process travel through LISTEN/NOTIFY.
    from apps.realtime import relay

    settings.REALTIME_RELAY = "postgres"
    layer = get_channel_layer()
    channel = await layer.new_channel()
    await layer.group_add(broadcast.trip_group(7), channel)
    try:
        await relay.ensure_listener()
        message = {"type": "broadcast.message", "event": "driver_location", "data": {"lat": 13.0}}
        await database_sync_to_async(relay.publish)(broadcast.trip_group(7), message)
        assert await asyncio.wait_for(layer.receive(channel), 5) == message

        # Oversized payloads shrink to a stub that tells clients to refetch.
        big = {
            "type": "broadcast.message",
            "event": "status",
            "data": {"id": 7, "blob": "x" * 9000},
        }
        await database_sync_to_async(relay.publish)(broadcast.trip_group(7), big)
        received = await asyncio.wait_for(layer.receive(channel), 5)
        assert received["data"] == {"id": 7, "partial": True}
    finally:
        await relay.stop()
