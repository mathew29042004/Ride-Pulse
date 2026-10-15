"""Chaos tests: break one outside dependency at a time and check the core business still works.

Real outages are partial: Redis or the task broker goes away, a push service or the SMS gateway
times out, Google's APIs fail, a payment gateway declines everything, a partner's webhook
endpoint is down. A ride must still be requested, matched, completed and paid; money must still
balance; and the failure must show up as a degraded extra, never as a failed trip.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
import requests

from apps.core.exceptions import DomainError
from apps.payments import services as payments
from apps.reliability import outbox
from apps.reliability.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


def boom(*args, **kwargs):
    raise ConnectionError("dependency is down")


def full_trip(mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    assert trip.status == "COMPLETED"
    return trip


def test_realtime_layer_down(mini, make_driver, now, monkeypatch):
    from asgiref import sync

    monkeypatch.setattr(sync, "async_to_sync", lambda fn: boom)
    monkeypatch.setattr("apps.realtime.relay.publish", boom)
    full_trip(mini, make_driver, now)


def test_task_broker_down(
    mini, make_driver, now, monkeypatch, admin, django_capture_on_commit_callbacks
):
    """Emails and push are queued after commit; a dead broker mustn't fail the request."""
    from apps.notifications import push, tasks

    monkeypatch.setattr(tasks.send_notification_email, "delay", boom)
    monkeypatch.setattr(tasks.send_push, "delay", boom)
    monkeypatch.setattr(push, "enabled", lambda: True)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        trip = full_trip(mini, make_driver, now)
        payments.refund_to_wallet(trip, Decimal("10"), reason="Chaos test", actor=admin)
    assert callbacks  # the after-commit work really ran (and failed quietly)
    assert payments.verify_ledger()["balanced"]


def test_maps_routing_down(mini, make_driver, now, monkeypatch, settings):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "get", boom)
    result = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    assert result["options"] and all(
        o["estimate"].route.source != "google" for o in result["options"]
    )


def test_translation_down(mini, make_driver, now, monkeypatch, settings):
    settings.GOOGLE_TRANSLATE_API_KEY = "test-key"
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "get", boom)
    make_driver(now=now)
    trip = book(make_rider(), mini, now=now)
    from apps.rides import dispatch

    from .helpers import pending_offer

    trip = dispatch.accept_offer(pending_offer(trip), driver=pending_offer(trip).driver, now=now)
    message = rides.send_message(trip, user=trip.rider.user, body="Wait near the blue gate please")
    assert message.pk  # sent untranslated rather than lost


def test_payment_gateway_down_for_upi_trip(mini, make_driver, now, monkeypatch):
    """The rider owes the fare instead; the trip still completes and the books balance."""
    from apps.payments import gateway

    monkeypatch.setattr(gateway, "charge", boom)
    trip = full_trip(mini, make_driver, now)
    assert trip.payment_status == "DUES"  # the rider owes it and pays from the app later
    assert payments.verify_ledger()["balanced"]


def test_top_up_with_gateway_down_is_a_clean_error(monkeypatch):
    from apps.payments import gateway

    monkeypatch.setattr(gateway, "charge", boom)
    rider = make_rider()
    before = payments.wallet_balance(rider.user)
    try:
        result = payments.top_up(rider.user, Decimal("200"), method="UPI", payer_reference="x@upi")
    except DomainError:
        result = None  # a clean, user-facing error is fine too
    if result is not None:
        payment = result[0] if isinstance(result, tuple) else result
        assert getattr(payment, "status", "FAILED") == "FAILED"
    assert payments.wallet_balance(rider.user) == before
    assert payments.verify_ledger()["balanced"]


def test_partner_webhook_down_retries_then_dead_letters(mini, make_driver, now, monkeypatch):
    endpoint = WebhookEndpoint.objects.create(
        name="Partner",
        url="https://partner.example/hook",
        secret="whsec_x",
        topics=["trip.completed"],
    )
    monkeypatch.setattr(requests, "post", boom)
    full_trip(mini, make_driver, now)
    assert outbox.relay(now=now) >= 1
    delivery = WebhookDelivery.objects.get(endpoint=endpoint)
    t = now
    for _ in range(outbox.MAX_ATTEMPTS):
        outbox.deliver_due(now=t)
        delivery.refresh_from_db()
        t = delivery.next_attempt_at + timedelta(seconds=1)
    assert delivery.status == DeliveryStatus.DEAD and delivery.attempts == outbox.MAX_ATTEMPTS
    assert "ConnectionError" in delivery.last_error
