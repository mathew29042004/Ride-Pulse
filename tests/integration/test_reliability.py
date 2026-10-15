"""Engineering depth: the transactional outbox and webhooks, account lockout and rate limits,
and offline GPS replay."""

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.drivers.models import LocationPing
from apps.reliability import outbox, security
from apps.reliability.models import (
    DeliveryStatus,
    OutboxEvent,
    SecurityEvent,
    SecurityKind,
    WebhookDelivery,
    WebhookEndpoint,
)
from apps.rides import dispatch

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture
def real_cache(settings):
    """Tests use a dummy cache; rate limits and the echo receiver need a real one."""
    settings.CACHES = LOCAL_CACHE
    cache.clear()
    yield
    cache.clear()


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_events_are_written_with_the_change_and_only_then(mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    topics = list(
        OutboxEvent.objects.filter(aggregate=f"trip:{trip.pk}").values_list("topic", flat=True)
    )
    assert topics == ["trip.requested", "trip.completed"]
    completed = OutboxEvent.objects.get(topic="trip.completed")
    assert completed.payload["trip_number"] == trip.trip_number
    assert "phone" not in json.dumps(completed.payload)  # no personal data in events

    # A rolled-back change leaves no event behind.
    before = OutboxEvent.objects.count()
    with pytest.raises(RuntimeError), transaction.atomic():
        outbox.emit("safety.sos", {"x": 1}, aggregate="incident:0")
        raise RuntimeError("the business change failed")
    assert OutboxEvent.objects.count() == before


def test_relay_signs_delivers_and_retries(mini, make_driver, now, monkeypatch):
    ok = WebhookEndpoint.objects.create(
        name="Partner", url="https://ok.example/hook", secret="whsec_a", topics=["trip.completed"]
    )
    flaky = WebhookEndpoint.objects.create(
        name="Flaky", url="https://flaky.example/hook", secret="whsec_b", topics=[]
    )
    sent = []

    def fake_post(url, data, headers, timeout):
        sent.append((url, data, headers))
        return FakeResponse(200 if "ok." in url else 503)

    monkeypatch.setattr(outbox.requests, "post", fake_post)
    make_driver(now=now)
    drive_to_completion(book(make_rider(), mini, now=now), now=now)
    assert outbox.relay(now=now) == 2  # requested + completed
    assert outbox.relay(now=now) == 0  # published once
    assert WebhookDelivery.objects.filter(endpoint=ok).count() == 1  # only its topic
    assert WebhookDelivery.objects.filter(endpoint=flaky).count() == 2  # every topic

    result = outbox.deliver_due(now=now)
    assert result == {"delivered": 1, "retrying": 2, "dead": 0}
    _url, body, headers = next(s for s in sent if "ok." in s[0])
    assert headers["X-RidePulse-Signature"] == outbox.sign("whsec_a", body)
    assert json.loads(body)["topic"] == "trip.completed"
    retry = WebhookDelivery.objects.filter(endpoint=flaky).first()
    assert retry.status == DeliveryStatus.RETRYING and retry.next_attempt_at == now + timedelta(
        seconds=30
    )
    assert outbox.deliver_due(now=now + timedelta(seconds=5))["retrying"] == 0  # not due yet


def test_echo_receiver_checks_signatures_and_dedupes(api, real_cache):
    cache.delete("webhooks:echo")
    endpoint = WebhookEndpoint.objects.create(
        name="Echo", url="http://127.0.0.1:8000/api/v1/webhooks/echo/", secret="whsec_echo"
    )
    body = json.dumps(
        {"id": "e1", "topic": "trip.completed", "created_at": "now", "data": {}}
    ).encode()
    client = api(None)
    bad = client.post(
        "/api/v1/webhooks/echo/",
        body,
        content_type="application/json",
        HTTP_X_RIDEPULSE_SIGNATURE="sha256=nope",
    )
    assert bad.status_code == 401
    good_sig = outbox.sign(endpoint.secret, body)
    for _ in range(2):  # a retried delivery arrives twice
        ok = client.post(
            "/api/v1/webhooks/echo/",
            body,
            content_type="application/json",
            HTTP_X_RIDEPULSE_SIGNATURE=good_sig,
        )
        assert ok.status_code == 200
    assert [e["id"] for e in cache.get("webhooks:echo")] == ["e1"]


def test_five_wrong_passwords_lock_the_account(api, rider):
    client = api(None)
    email = rider.user.email
    for _ in range(4):
        r = client.post("/api/v1/auth/token/", {"email": email, "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/token/", {"email": email, "password": "wrong"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"
    right = client.post("/api/v1/auth/token/", {"email": email, "password": "pw-12345!"})
    assert right.status_code == 429  # even the right password waits out the lock
    assert rider.user.notifications.filter(title__startswith="We locked your account").exists()
    assert SecurityEvent.objects.filter(kind=SecurityKind.LOCKED, email=email).exists()

    security.unlock(email, actor=rider.user)
    assert (
        client.post("/api/v1/auth/token/", {"email": email, "password": "pw-12345!"}).status_code
        == 200
    )


def test_booking_is_rate_limited_but_sos_never_is(
    api, rider, mini, make_driver, now, settings, real_cache, monkeypatch
):
    from django.conf import settings as conf

    rates = {**conf.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "booking": "2/hour"}
    settings.REST_FRAMEWORK = {**conf.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", rates)  # restored afterwards
    cache.clear()
    client = api(rider.user)
    body = {
        "ride_type": "MINI",
        "payment_method": "UPI",
        "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
        "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
    }
    from apps.rides import services as rides
    from apps.rides.models import Trip

    for _ in range(2):
        created = client.post("/api/v1/trips/", body, format="json")
        assert created.status_code == 201
        rides.cancel_trip(Trip.objects.get(pk=created.json()["id"]), user=rider.user)
    third = client.post("/api/v1/trips/", body, format="json")
    assert third.status_code == 429
    assert SecurityEvent.objects.filter(kind=SecurityKind.THROTTLED, path="/api/v1/trips/").exists()

    make_driver(now=now)
    trip = book(make_rider(), mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=pending_offer(trip).driver, now=now)
    sos_client = api(trip.rider.user)
    for _ in range(3):
        assert sos_client.post(f"/api/v1/trips/{trip.pk}/sos/", {"note": "help"}).status_code == 201


def test_offline_gps_fixes_replay_in_order(api, make_driver, now):
    driver = make_driver(now=timezone.now())
    client = api(driver.user)
    t0 = timezone.now() - timedelta(minutes=5)
    fixes = [
        {
            "lat": 13.05 + i * 0.001,
            "lng": 80.24,
            "recorded_at": (t0 + timedelta(seconds=10 * i)).isoformat(),
        }
        for i in (2, 0, 1)  # arrives out of order
    ]
    assert (
        client.post("/api/v1/driver/location/batch/", {"fixes": fixes}, format="json").status_code
        == 204
    )
    trail = [
        round(lat, 4)
        for lat in LocationPing.objects.filter(
            driver=driver, recorded_at__gte=t0, recorded_at__lte=t0 + timedelta(minutes=1)
        )
        .order_by("pk")
        .values_list("lat", flat=True)
    ]
    assert trail == [13.05, 13.051, 13.052]  # stored in the order they were taken
    driver.refresh_from_db()
    assert round(driver.current_lat, 4) == 13.052
    stale = [
        {"lat": 13.0, "lng": 80.0, "recorded_at": (timezone.now() - timedelta(hours=2)).isoformat()}
    ]
    assert (
        client.post("/api/v1/driver/location/batch/", {"fixes": stale}, format="json").status_code
        == 400
    )
