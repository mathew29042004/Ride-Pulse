"""Demo: a webhook endpoint pointing at the built-in echo receiver, so outbox events are
delivered (and signed) end to end while the simulator runs."""

from django.conf import settings

from . import outbox
from .models import WebhookEndpoint

ECHO_URL = "http://127.0.0.1:8000/api/v1/webhooks/echo/"


def seed(*, log=print) -> dict:
    if WebhookEndpoint.objects.exists() or not settings.DEMO_MODE:
        return {"webhooks": 0}
    WebhookEndpoint.objects.create(
        name="Demo receiver (built-in echo)",
        url=ECHO_URL,
        secret=outbox.new_secret(),
        topics=["trip.completed", "trip.cancelled", "safety.sos", "payout.created"],
    )
    log("  webhook endpoint → built-in echo receiver")
    return {"webhooks": 1}
