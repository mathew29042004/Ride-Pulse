"""Feature flags (switch a feature on for some people) and A/B tests (measure what it does)."""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class FeatureFlag(models.Model):
    """On for ``rollout_percent`` of people (by a stable hash of their id), plus an allow list."""

    key = models.SlugField(max_length=60, unique=True)
    description = models.CharField(max_length=200)
    enabled = models.BooleanField(default=False)  # the kill switch: off means off for everyone
    rollout_percent = models.PositiveSmallIntegerField(default=100)
    allow_user_ids = ArrayField(models.IntegerField(), default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key


class ExperimentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    RUNNING = "RUNNING", "Running"
    STOPPED = "STOPPED", "Stopped"


class Experiment(models.Model):
    """A/B test: people are split between ``control`` and ``treatment`` (stable per person) and
    each exposure (they saw the variant) is checked for a conversion (they then booked)."""

    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    hypothesis = models.TextField()
    status = models.CharField(
        max_length=8, choices=ExperimentStatus.choices, default=ExperimentStatus.DRAFT
    )
    treatment_percent = models.PositiveSmallIntegerField(default=50)
    # What the treatment changes, read by the code that runs it (e.g. {"surge_cap": "2.0"}).
    treatment_config = models.JSONField(default=dict, blank=True)
    primary_metric = models.CharField(max_length=40, default="conversion")
    # The smallest change worth detecting (absolute, e.g. 0.03 = 3 percentage points).
    minimum_effect = models.FloatField(default=0.03)
    started_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    decision = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-started_at", "key"]

    def __str__(self) -> str:
        return self.key


class Variant(models.TextChoices):
    CONTROL = "control", "Control (A)"
    TREATMENT = "treatment", "Treatment (B)"


class Exposure(models.Model):
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="exposures")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    variant = models.CharField(max_length=9, choices=Variant.choices)
    at = models.DateTimeField(db_index=True)
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["experiment", "variant"], name="exposure_exp_variant_idx")]

    def __str__(self) -> str:
        return f"{self.experiment_id} {self.user_id} {self.variant}"
