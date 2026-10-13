from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Created"
    UPDATE = "UPDATE", "Updated"
    DELETE = "DELETE", "Deleted"
    TRANSITION = "TRANSITION", "Status change"
    ACTION = "ACTION", "Business action"


class AuditLog(models.Model):
    """Append-only record of who changed what. Never updated after insert."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=12, choices=AuditAction.choices)
    entity_type = models.CharField(max_length=60)
    entity_id = models.CharField(max_length=64)
    entity_label = models.CharField(max_length=200, blank=True)
    message = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # Rows arrive in time order, so a BRIN index on created_at is tiny compared with a
            # B-tree yet still prunes date-range scans of a table that only ever grows.
            BrinIndex(fields=["created_at"], name="audit_created_brin"),
            models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.entity_type}#{self.entity_id}"
