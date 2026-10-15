"""Transactional outbox, webhooks, and security events."""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q


class OutboxEvent(models.Model):
    """An event saved in the same database transaction as the change it describes, so it can
    never be lost (crash after commit) or sent for a change that rolled back. A relay publishes
    it afterwards, at least once; consumers dedupe on ``id``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=60, db_index=True)
    aggregate = models.CharField(max_length=40)  # e.g. "trip:123"
    payload = models.JSONField()
    created_at = models.DateTimeField(db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=Q(published_at__isnull=True),
                name="outbox_unpublished_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.topic} {self.aggregate}"


class WebhookEndpoint(models.Model):
    """Someone outside who wants events: a URL, the topics, and a secret for signatures."""

    name = models.CharField(max_length=80)
    url = models.URLField(max_length=300)
    secret = models.CharField(max_length=64)
    topics = ArrayField(models.CharField(max_length=60), default=list)  # empty = every topic
    # A corporate account's own endpoint only receives its employees' events.
    corporate = models.ForeignKey(
        "riders.PaymentProfile",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="webhooks",
    )
    is_active = models.BooleanField(default=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    disabled_reason = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting to send"
    DELIVERED = "DELIVERED", "Delivered"
    RETRYING = "RETRYING", "Failed, will retry"
    DEAD = "DEAD", "Gave up (dead letter)"


class WebhookDelivery(models.Model):
    event = models.ForeignKey(OutboxEvent, on_delete=models.CASCADE, related_name="deliveries")
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-next_attempt_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "endpoint"], name="one_delivery_per_endpoint")
        ]

    def __str__(self) -> str:
        return f"{self.event_id} → {self.endpoint_id}: {self.status}"


class SecurityKind(models.TextChoices):
    LOGIN_FAILED = "LOGIN_FAILED", "Wrong password"
    LOCKED = "LOCKED", "Account locked"
    UNLOCKED = "UNLOCKED", "Account unlocked"
    THROTTLED = "THROTTLED", "Rate limited"


class SecurityEvent(models.Model):
    kind = models.CharField(max_length=12, choices=SecurityKind.choices)
    email = models.CharField(max_length=254, blank=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.email or self.ip}"
