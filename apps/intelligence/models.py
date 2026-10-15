"""Ops intelligence: automatic alerts, the morning briefing, demand nudges and fraud cases."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class AlertKind(models.TextChoices):
    HIGH_CANCELLATIONS = "HIGH_CANCELLATIONS", "Many cancellations"
    LOW_SUPPLY = "LOW_SUPPLY", "Not enough drivers"
    SOS_SPIKE = "SOS_SPIKE", "SOS spike"
    SUPPORT_BACKLOG = "SUPPORT_BACKLOG", "Support tickets past SLA"


class AlertStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    RESOLVED = "RESOLVED", "Resolved"


class OpsAlert(models.Model):
    """Raised when a city's numbers go wrong; it creates a task for the manager who owns it and
    resolves itself once the numbers recover."""

    kind = models.CharField(max_length=20, choices=AlertKind.choices)
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="alerts")
    severity = models.CharField(max_length=8, default="WARNING")  # WARNING or CRITICAL
    title = models.CharField(max_length=160)
    detail = models.TextField()
    metrics = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=AlertStatus.choices, default=AlertStatus.OPEN)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    task = models.ForeignKey(
        "workspace.WorkTask", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "city"],
                condition=Q(status="OPEN"),
                name="one_open_alert_per_kind_city",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.city_id}"


class DailyBriefing(models.Model):
    """Yesterday in numbers, written every morning for leadership."""

    day = models.DateField(unique=True)
    data = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-day"]

    def __str__(self) -> str:
        return f"Briefing {self.day}"


class DemandNudge(models.Model):
    """A driver was told demand is about to rise in a zone (also rate-limits nudges)."""

    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="demand_nudges"
    )
    zone = models.ForeignKey("geo.Zone", on_delete=models.CASCADE, related_name="+")
    expected_trips = models.PositiveIntegerField()
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.driver_id} → {self.zone_id}"


class FraudKind(models.TextChoices):
    GPS_SPOOFING = "GPS_SPOOFING", "GPS spoofing"
    ROUTE_PADDING = "ROUTE_PADDING", "Route padding (long detours)"
    COLLUSION = "COLLUSION", "Same rider and driver again and again"
    PROMO_ABUSE = "PROMO_ABUSE", "Promo codes on very short trips"
    REFERRAL_FARMING = "REFERRAL_FARMING", "Referral farming"


class FraudStatus(models.TextChoices):
    OPEN = "OPEN", "Needs review"
    CONFIRMED = "CONFIRMED", "Confirmed fraud"
    DISMISSED = "DISMISSED", "Not fraud"


class FraudCase(models.Model):
    number = models.CharField(max_length=20, unique=True)
    kind = models.CharField(max_length=20, choices=FraudKind.choices)
    driver = models.ForeignKey(
        "drivers.DriverProfile", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    rider = models.ForeignKey(
        "riders.RiderProfile", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    score = models.PositiveSmallIntegerField()  # 0-100, how strong the evidence is
    summary = models.CharField(max_length=255)
    evidence = models.JSONField(default=dict)
    trip_ids = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=FraudStatus.choices, default=FraudStatus.OPEN)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    action_taken = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-score", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "driver", "rider"],
                condition=Q(status="OPEN"),
                name="one_open_fraud_case",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=Q(driver__isnull=False) | Q(rider__isnull=False),
                name="fraud_case_has_subject",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.get_kind_display()}"
