from django.conf import settings
from django.db import models
from django.utils import timezone


class Level(models.TextChoices):
    INFO = "INFO", "Info"
    SUCCESS = "SUCCESS", "Success"
    WARNING = "WARNING", "Warning"
    DANGER = "DANGER", "Urgent"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Kept quiet (no pop-up) by the person's preferences: quiet hours or the daily digest.
    held = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                condition=models.Q(is_read=False),
                name="notification_unread_idx",
            )
        ]

    def __str__(self) -> str:
        return self.title


class PushSubscription(models.Model):
    """A browser/device that accepted Web Push for this user (one row per device)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.user_id} {self.endpoint[:40]}"


class NotificationPreference(models.Model):
    """Quiet hours (no pop-ups except urgent ones) and the daily digest (routine updates held and
    summed up once a morning). Everything still appears in the bell list straight away."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference"
    )
    quiet_from = models.PositiveSmallIntegerField(null=True, blank=True)  # hour, 0–23
    quiet_until = models.PositiveSmallIntegerField(null=True, blank=True)
    digest = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Preferences for {self.user_id}"

    def is_quiet(self, when) -> bool:
        if (
            self.quiet_from is None
            or self.quiet_until is None
            or self.quiet_from == self.quiet_until
        ):
            return False
        hour = timezone.localtime(when).hour
        if self.quiet_from < self.quiet_until:
            return self.quiet_from <= hour < self.quiet_until
        return hour >= self.quiet_from or hour < self.quiet_until  # e.g. 22 → 7
