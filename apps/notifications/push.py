"""Web Push: notifications that reach a phone or desktop even when Ride Pulse isn't open
(trip offers for drivers, "driver arrived" for riders). Standard VAPID Web Push, so no Firebase
account is needed: works in Chrome/Edge/Firefox, Android, and iPhone home-screen apps.

Enabled when VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are set (``manage.py generate_vapid_keys``).
Subscriptions the push service reports as gone (404/410) are deleted.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

from .models import PushSubscription

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send(
    user_id: int,
    *,
    title: str,
    body: str = "",
    url: str = "/",
    tag: str = "",
    ttl: int = 3600,
    urgent: bool = False,
) -> int:
    """Push to every device of a user. Returns how many deliveries the push services accepted."""
    from pywebpush import WebPushException, webpush

    if not enabled():
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    delivered = 0
    for sub in PushSubscription.objects.filter(user_id=user_id):
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=ttl,
                headers={"Urgency": "high" if urgent else "normal"},
                timeout=5,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):  # the browser unsubscribed or the app was uninstalled
                sub.delete()
            else:
                logger.warning("Web push to %s failed: %s", sub.pk, exc)
            continue
        except Exception:  # network trouble: push is best-effort
            logger.warning("Web push to %s failed", sub.pk, exc_info=True)
            continue
        delivered += 1
        PushSubscription.objects.filter(pk=sub.pk).update(last_success_at=timezone.now())
    return delivered
