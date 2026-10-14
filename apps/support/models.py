from django.conf import settings
from django.db import models

from apps.audit.mixins import AuditedModel
from apps.core.models import LatitudeField, LongitudeField, TimeStampedModel


class TicketCategory(models.TextChoices):
    FARE_DISPUTE = "FARE_DISPUTE", "Fare dispute"
    PAYMENT = "PAYMENT", "Payment problem"
    LOST_ITEM = "LOST_ITEM", "Lost item"
    DRIVER_BEHAVIOUR = "DRIVER_BEHAVIOUR", "Driver behaviour"
    RIDER_BEHAVIOUR = "RIDER_BEHAVIOUR", "Rider behaviour"
    SAFETY = "SAFETY", "Safety"
    APP_ISSUE = "APP_ISSUE", "App problem"
    OTHER = "OTHER", "Something else"


class TicketPriority(models.TextChoices):
    URGENT = "URGENT", "Urgent"
    HIGH = "HIGH", "High"
    NORMAL = "NORMAL", "Normal"
    LOW = "LOW", "Low"


CATEGORY_PRIORITY = {
    TicketCategory.SAFETY: TicketPriority.URGENT,
    TicketCategory.FARE_DISPUTE: TicketPriority.HIGH,
    TicketCategory.PAYMENT: TicketPriority.HIGH,
    TicketCategory.DRIVER_BEHAVIOUR: TicketPriority.HIGH,
    TicketCategory.RIDER_BEHAVIOUR: TicketPriority.NORMAL,
    TicketCategory.LOST_ITEM: TicketPriority.NORMAL,
    TicketCategory.APP_ISSUE: TicketPriority.LOW,
    TicketCategory.OTHER: TicketPriority.LOW,
}


class TicketStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    WAITING_ON_USER = "WAITING_ON_USER", "Waiting on user"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"


OPEN_TICKET_STATUSES = [TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_USER]


class SupportTicket(AuditedModel, TimeStampedModel):
    ticket_number = models.CharField(max_length=24, unique=True)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets_raised"
    )
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    category = models.CharField(max_length=16, choices=TicketCategory.choices)
    priority = models.CharField(max_length=6, choices=TicketPriority.choices)
    status = models.CharField(
        max_length=15, choices=TicketStatus.choices, default=TicketStatus.OPEN
    )
    subject = models.CharField(max_length=160)
    description = models.TextField()
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_assigned",
    )
    sla_due_at = models.DateTimeField()
    escalated = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"], name="ticket_queue_idx"),
            models.Index(fields=["assigned_to", "status"], name="ticket_assignee_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_number}: {self.subject}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_TICKET_STATUSES


class TicketMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    is_internal = models.BooleanField(default=False, help_text="Staff-only note")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.ticket_id} by {self.author_id}"


class IncidentStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    RESOLVED = "RESOLVED", "Resolved"


class SafetyIncident(TimeStampedModel):
    """An SOS raised from an active trip. Routed to the safety desk with top priority."""

    incident_number = models.CharField(max_length=24, unique=True)
    trip = models.ForeignKey("rides.Trip", on_delete=models.PROTECT, related_name="incidents")
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    lat = LatitudeField(null=True, blank=True)
    lng = LongitudeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    ambulance_requested = models.BooleanField(default=False)
    status = models.CharField(
        max_length=12, choices=IncidentStatus.choices, default=IncidentStatus.OPEN
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    ticket = models.OneToOneField(
        SupportTicket, null=True, blank=True, on_delete=models.SET_NULL, related_name="incident"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["-created_at"],
                condition=models.Q(status="OPEN"),
                name="incident_open_idx",
            )
        ]

    def __str__(self) -> str:
        return self.incident_number


class TripRecordingKey(models.Model):
    """The key one trip participant's app encrypts its audio recording with. Stored wrapped
    (encrypted with a key derived from the server secret), never in the clear."""

    trip = models.ForeignKey("rides.Trip", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    wrapped_key = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "user"], name="one_recording_key_per_user"),
        ]

    def __str__(self) -> str:
        return f"Recording key for {self.user_id} on {self.trip_id}"


class SafetyRecording(models.Model):
    """An encrypted trip audio recording a rider or driver shared with the safety team."""

    trip = models.ForeignKey("rides.Trip", on_delete=models.PROTECT, related_name="recordings")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    ticket = models.ForeignKey(
        SupportTicket, null=True, blank=True, on_delete=models.SET_NULL, related_name="recordings"
    )
    ciphertext = models.FileField(upload_to="safety-recordings/%Y/%m/")
    iv = models.BinaryField()
    mime_type = models.CharField(max_length=60, default="audio/webm")
    duration_seconds = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Recording {self.pk} on {self.trip_id}"
