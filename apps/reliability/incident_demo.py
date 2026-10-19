"""Demo incidents: two from the last fortnight, resolved, one with its review."""

from datetime import timedelta

from django.utils import timezone

from . import incidents
from .models import Incident


def seed(*, log=print) -> dict:
    if Incident.objects.exists():
        return {"incidents": 0}
    from apps.accounts.models import User

    ops = User.objects.filter(email="admin@ridepulse.dev").first()
    now = timezone.now()
    first = incidents.open_incident(
        user=ops,
        title="Card payments failing",
        severity="MAJOR",
        components=["PAYMENTS"],
        public_message="Card payments are delayed. UPI, wallet and cash work as usual.",
        now=now - timedelta(days=6, hours=3),
    )
    incidents.update(
        first,
        user=ops,
        status="IDENTIFIED",
        message="The gateway's API key expired.",
        now=now - timedelta(days=6, hours=2, minutes=40),
    )
    incidents.update(
        first,
        user=ops,
        status="RESOLVED",
        message="New key in place; card payments verified.",
        now=now - timedelta(days=6, hours=2, minutes=20),
    )
    first.refresh_from_db()
    incidents.review(
        first,
        user=ops,
        summary="Card payments failed for 40 minutes after the payment gateway's API key expired. "
        "About 300 riders paid by UPI or cash instead; no fares were lost.",
        root_cause="Nobody was alerted before the gateway key expired.",
        actions=[],
        now=now - timedelta(days=5),
    )
    second = incidents.open_incident(
        user=ops,
        title="Slow ETAs in Bengaluru",
        severity="MINOR",
        components=["MAPS"],
        public_message="Arrival times may be a few minutes off in Bengaluru.",
        now=now - timedelta(days=2, hours=5),
    )
    incidents.update(
        second,
        user=ops,
        status="RESOLVED",
        message="The traffic data feed caught up.",
        now=now - timedelta(days=2, hours=4),
    )
    log("Incidents: 2 resolved in the last fortnight")
    return {"incidents": 2}


def seed_weather(*, log=print) -> dict:
    """A past Chennai flood (ended) and heavy rain on now in Kochi (rain only caps surge)."""
    from apps.accounts.models import User
    from apps.geo.models import City

    from . import weather
    from .models import WeatherAlert

    if WeatherAlert.objects.exists():
        return {"weather_alerts": 0}
    ops = User.objects.filter(email="admin@ridepulse.dev").first()
    now = timezone.now()
    made = 0
    with notifications_muted():
        chennai = City.objects.filter(slug="chennai").first()
        if chennai:
            flooded = list(chennai.zones.all()[:2])
            past = weather.start(
                city=chennai,
                level="FLOOD",
                user=ops,
                hours=18,
                zones=flooded,
                now=now - timedelta(days=9),
            )
            made += bool(past)
        kochi = City.objects.filter(slug="kochi").first()
        if kochi:
            weather.start(
                city=kochi,
                level="RAIN",
                user=ops,
                hours=12,
                message="IMD orange alert: heavy rain. Rides may take longer; surge capped at 1.5x.",
                now=now - timedelta(hours=1),
            )
            made += 1
    log(f"  weather alerts: {made}")
    return {"weather_alerts": made}


def notifications_muted():
    from apps.notifications import services as notifications

    return notifications.muted()
