from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Sequence(models.Model):
    """Gap-free counters behind human-readable reference numbers (TRP-2026-000123)."""

    key = models.CharField(max_length=40, primary_key=True)
    last_value = models.PositiveBigIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.key}={self.last_value}"


def LatitudeField(**kwargs):
    return models.FloatField(validators=[MinValueValidator(-90), MaxValueValidator(90)], **kwargs)


def LongitudeField(**kwargs):
    return models.FloatField(validators=[MinValueValidator(-180), MaxValueValidator(180)], **kwargs)
