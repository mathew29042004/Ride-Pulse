"""The transactional outbox and webhook delivery.

1. ``emit(topic, payload)`` inside the business transaction writes an ``OutboxEvent`` row. If the
   transaction rolls back, so does the event; if it commits, the event is safely stored even if
   the process dies a millisecond later. (Publishing straight to a broker or a webhook from inside
   the transaction can't promise either.)
2. ``relay()`` (every few seconds) takes unpublished events with ``SELECT … FOR UPDATE SKIP
   LOCKED`` so several workers never grab the same row, fans each one out to the webhook
   endpoints subscribed to its topic, and marks it published.
3. ``deliver_due()`` POSTs each delivery, signed with HMAC-SHA256 over the body
   (``X-RidePulse-Signature: sha256=…``) and carrying the event id for idempotent consumers.
   Failures retry with exponential backoff (30 s, 1, 2, 4 … minutes, capped at an hour); after 8
   attempts the delivery is dead-lettered for ops to replay. An endpoint that keeps failing is
   switched off.
"""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

import requests
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone

from .models import DeliveryStatus, OutboxEvent, WebhookDelivery, WebhookEndpoint

MAX_ATTEMPTS = 8
DISABLE_AFTER = 50  # consecutive failures across deliveries
TIMEOUT_SECONDS = 5
TOPICS = {
    "trip.requested": "A rider requested a trip",
    "trip.completed": "A trip finished and was paid",
    "trip.cancelled": "A trip was cancelled",
    "payment.refunded": "A refund was issued",
    "payout.created": "A weekly payout was sent",
    "safety.sos": "Someone pressed SOS",
    "fraud.case_opened": "A fraud case was opened",
}


def emit(topic: str, payload: dict, *, aggregate: str, at: datetime | None = None) -> OutboxEvent:
    """Record an event in the current transaction."""
    if topic not in TOPICS:
        raise ValueError(f"Unknown topic {topic}")
    body = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
    return OutboxEvent.objects.create(
        topic=topic, aggregate=aggregate, payload=body, created_at=at or timezone.now()
    )


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def new_secret() -> str:
    return "whsec_" + secrets.token_hex(24)


def _subscribers(event: OutboxEvent):
    endpoints = WebhookEndpoint.objects.filter(is_active=True).filter(
        Q(topics=[]) | Q(topics__contains=[event.topic])
    )
    profile_id = event.payload.get("payment_profile_id")
    # Corporate endpoints only hear about their own employees' trips.
    return [e for e in endpoints if e.corporate_id is None or e.corporate_id == profile_id]


def relay(*, batch: int = 200, now: datetime | None = None) -> int:
    now = now or timezone.now()
    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True)
            .order_by("created_at")[:batch]
        )
        for event in events:
            WebhookDelivery.objects.bulk_create(
                [
                    WebhookDelivery(event=event, endpoint=endpoint, next_attempt_at=now)
                    for endpoint in _subscribers(event)
                ],
                ignore_conflicts=True,
            )
        OutboxEvent.objects.filter(pk__in=[e.pk for e in events]).update(published_at=now)
    return len(events)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


def _post(delivery: WebhookDelivery) -> tuple[int | None, str]:
    event = delivery.event
    body = json.dumps(
        {
            "id": str(event.id),
            "topic": event.topic,
            "created_at": event.created_at.isoformat(),
            "data": event.payload,
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RidePulse-Webhooks/1.0",
        "X-RidePulse-Event": str(event.id),
        "X-RidePulse-Topic": event.topic,
        "X-RidePulse-Signature": sign(delivery.endpoint.secret, body),
    }
    try:
        response = requests.post(
            delivery.endpoint.url, data=body, headers=headers, timeout=TIMEOUT_SECONDS
        )
    except Exception as exc:  # any failure at the partner's end is theirs, never a crash here
        return None, type(exc).__name__
    if 200 <= response.status_code < 300:
        return response.status_code, ""
    return response.status_code, f"HTTP {response.status_code}"


LEASE = timedelta(minutes=2)


def deliver_due(*, now: datetime | None = None, limit: int = 100) -> dict:
    """Claim due deliveries in a short transaction (a lease, so another worker skips them), send
    them outside any transaction (network calls must never hold database locks), then record
    each result."""
    now = now or timezone.now()
    with transaction.atomic():
        claimed = list(
            WebhookDelivery.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                status__in=[DeliveryStatus.PENDING, DeliveryStatus.RETRYING],
                next_attempt_at__lte=now,
                endpoint__is_active=True,
            )
            .order_by("next_attempt_at")
            .values_list("pk", flat=True)[:limit]
        )
        WebhookDelivery.objects.filter(pk__in=claimed).update(next_attempt_at=now + LEASE)
    counts = {"delivered": 0, "retrying": 0, "dead": 0}
    for delivery in WebhookDelivery.objects.filter(pk__in=claimed).select_related(
        "event", "endpoint"
    ):
        code, error = _post(delivery)
        counts[_record(delivery, code, error, now)] += 1
    return counts


def _record(delivery: WebhookDelivery, code: int | None, error: str, now: datetime) -> str:
    delivery.attempts += 1
    delivery.last_status_code = code
    endpoint = delivery.endpoint
    if not error:
        delivery.status, delivery.delivered_at, delivery.last_error = (
            DeliveryStatus.DELIVERED,
            now,
            "",
        )
        WebhookEndpoint.objects.filter(pk=endpoint.pk).update(consecutive_failures=0)
        outcome = "delivered"
    else:
        delivery.last_error = error[:255]
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status, outcome = DeliveryStatus.DEAD, "dead"
        else:
            delivery.status, outcome = DeliveryStatus.RETRYING, "retrying"
            delivery.next_attempt_at = now + backoff(delivery.attempts)
        failures = endpoint.consecutive_failures + 1
        update = {"consecutive_failures": failures}
        if failures >= DISABLE_AFTER:
            update |= {"is_active": False, "disabled_reason": f"{failures} failures in a row"}
        WebhookEndpoint.objects.filter(pk=endpoint.pk).update(**update)
    delivery.save()
    return outcome


def replay(delivery: WebhookDelivery) -> WebhookDelivery:
    """Ops: send a dead-lettered delivery again."""
    delivery.status, delivery.attempts = DeliveryStatus.PENDING, 0
    delivery.next_attempt_at = timezone.now()
    delivery.save(update_fields=["status", "attempts", "next_attempt_at"])
    return delivery


def health(*, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    pending = OutboxEvent.objects.filter(published_at__isnull=True)
    oldest = pending.aggregate(at=Min("created_at"))["at"]
    by_status = dict(
        WebhookDelivery.objects.values_list("status")
        .annotate(n=Count("pk"))
        .values_list("status", "n")
    )
    last_hour = OutboxEvent.objects.filter(created_at__gte=now - timedelta(hours=1))
    return {
        "unpublished": pending.count(),
        "lag_seconds": round((now - oldest).total_seconds()) if oldest else 0,
        "events_last_hour": last_hour.count(),
        "by_topic_last_hour": dict(
            last_hour.values_list("topic").annotate(n=Count("pk")).values_list("topic", "n")
        ),
        "deliveries": by_status,
        "endpoints": WebhookEndpoint.objects.count(),
        "disabled_endpoints": WebhookEndpoint.objects.filter(is_active=False).count(),
    }
