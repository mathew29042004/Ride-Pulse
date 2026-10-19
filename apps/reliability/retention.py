"""Keeping the database lean: every night, rows nobody needs any more are deleted in batches.

What goes, and when (everything else, trips, money, audit, HR, is kept):

(Driver location pings have their own job: ``drivers.purge_location_pings``.)

* read notifications: after 90 days; unread ones after 180;
* published outbox events: after 30 days; delivered webhooks: after 30 days;
* surge snapshots and weather readings: after 90 days (the forecasts only look back 8 weeks).
"""

from datetime import timedelta

from django.utils import timezone

BATCH = 5000


def _purge(qs) -> int:
    """Delete in batches so a big backlog doesn't lock the table for long."""
    total = 0
    while True:
        ids = list(qs.values_list("pk", flat=True)[:BATCH])
        if not ids:
            return total
        total += qs.model.objects.filter(pk__in=ids).delete()[0]


def prune(*, now=None) -> dict:
    from apps.intelligence.models import WeatherReading
    from apps.notifications.models import Notification
    from apps.pricing.models import SurgeSnapshot

    from .models import OutboxEvent, WebhookDelivery

    now = now or timezone.now()
    days = lambda n: now - timedelta(days=n)  # noqa: E731
    return {
        "notifications": _purge(Notification.objects.filter(is_read=True, created_at__lt=days(90)))
        + _purge(Notification.objects.filter(created_at__lt=days(180))),
        "outbox": _purge(
            OutboxEvent.objects.filter(published_at__isnull=False, created_at__lt=days(30))
        ),
        "webhooks": _purge(
            WebhookDelivery.objects.filter(delivered_at__isnull=False, delivered_at__lt=days(30))
        ),
        "surge_snapshots": _purge(SurgeSnapshot.objects.filter(computed_at__lt=days(90))),
        "weather": _purge(WeatherReading.objects.filter(observed_at__lt=days(90))),
    }
