"""Announcements: ops write once (English, with Tamil and Hindi if they like), choose who and
where, and everyone reads it in their own app language; ops see who has read it."""

from django.conf import settings
from django.db import models


class Audience(models.TextChoices):
    DRIVERS = "DRIVERS", "Drivers"
    RIDERS = "RIDERS", "Riders"
    STAFF = "STAFF", "Staff"


class Announcement(models.Model):
    audience = models.CharField(max_length=7, choices=Audience.choices)
    state = models.CharField(max_length=60, blank=True)  # blank: everywhere
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # {"en": {"title": …, "body": …}, "ta": {…}, "hi": {…}}; English is required.
    text = models.JSONField()
    important = models.BooleanField(default=False)  # pinned on the home screen until read
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    published_at = models.DateTimeField(db_index=True)
    recipients = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return self.text.get("en", {}).get("title", "")

    def localized(self, language: str) -> dict:
        return self.text.get(language) or self.text["en"]


class AnnouncementRead(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["announcement", "user"], name="announcement_read_once")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} read {self.announcement_id}"
