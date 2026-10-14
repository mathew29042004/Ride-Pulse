"""Price-drop alerts: while a route is surging, a rider can ask to be told when it eases.

The watcher only reads the pickup zone's surge (cheap: no routing calls). When the multiplier
is back to normal, or at least 15% lower than when the alert was set, it prices the trip once
and notifies the rider (in-app and push) with a link that opens booking on that route.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.geo.services import require_city, zone_for_point
from apps.notifications.models import Level
from apps.notifications.services import notify

from . import passes, services
from .models import PriceAlert, PriceAlertStatus, RideType

ALERT_LIFETIME = timedelta(hours=2)
MAX_ACTIVE = 3
DROP_FACTOR = Decimal("0.85")


def create_alert(
    rider,
    *,
    ride_type: RideType,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    pickup_address: str = "",
    dropoff_address: str = "",
    now: datetime | None = None,
) -> PriceAlert:
    now = now or timezone.now()
    if (
        rider.price_alerts.filter(status=PriceAlertStatus.ACTIVE, expires_at__gt=now).count()
        >= MAX_ACTIVE
    ):
        raise ConflictError(f"You can watch up to {MAX_ACTIVE} routes at a time.")
    city = require_city(*pickup)
    estimate = services.estimate_fare(
        city=city,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=dropoff,
        at=now,
        ride_pass=passes.active_pass(rider, now) is not None,
    )
    if estimate.surge_multiplier <= 1:
        raise BusinessRuleViolation("Prices are already at their normal level. Book now!")
    return PriceAlert.objects.create(
        rider=rider,
        ride_type=ride_type,
        city=city,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        pickup_address=pickup_address[:255],
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        dropoff_address=dropoff_address[:255],
        fare_when_set=estimate.fare.total,
        surge_when_set=estimate.surge_multiplier,
        expires_at=now + ALERT_LIFETIME,
    )


def check_alerts(*, now: datetime | None = None) -> dict:
    """Notify riders whose watched routes are no longer surging. Run every couple of minutes."""
    now = now or timezone.now()
    stats = {"notified": 0, "expired": 0}
    stats["expired"] = PriceAlert.objects.filter(
        status=PriceAlertStatus.ACTIVE, expires_at__lte=now
    ).update(status=PriceAlertStatus.EXPIRED)
    alerts = PriceAlert.objects.filter(status=PriceAlertStatus.ACTIVE).select_related(
        "rider__user", "ride_type", "city"
    )
    zones_by_city: dict[int, list] = {}
    for alert in alerts:
        zones = zones_by_city.setdefault(alert.city_id, list(alert.city.zones.all()))
        zone = zone_for_point(alert.city, alert.pickup_lat, alert.pickup_lng, zones)
        surge = services.current_surge(zone, now=now)
        if surge > 1 and surge > alert.surge_when_set * DROP_FACTOR:
            continue
        with transaction.atomic():
            claimed = PriceAlert.objects.filter(pk=alert.pk, status=PriceAlertStatus.ACTIVE).update(
                status=PriceAlertStatus.NOTIFIED, notified_at=now
            )
            if not claimed:
                continue  # another worker got it
            estimate = services.estimate_fare(
                city=alert.city,
                ride_type=alert.ride_type,
                pickup=(alert.pickup_lat, alert.pickup_lng),
                dropoff=(alert.dropoff_lat, alert.dropoff_lng),
                at=now,
                ride_pass=passes.active_pass(alert.rider, now) is not None,
            )
            fare = estimate.fare.total
            PriceAlert.objects.filter(pk=alert.pk).update(fare_when_notified=fare)
            destination = alert.dropoff_address or "your destination"
            notify(
                alert.rider.user,
                f"Prices dropped: {alert.ride_type.name} now ₹{fare:,.0f}",
                f"To {destination} (was ₹{alert.fare_when_set:,.0f}). Book while it lasts.",
                level=Level.SUCCESS,
                link=f"/ride/book?to={alert.dropoff_lat},{alert.dropoff_lng}&name={quote(destination)}",
            )
        stats["notified"] += 1
    return stats
