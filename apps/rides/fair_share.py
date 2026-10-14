"""Fair Share Meter: where every rupee of a fare goes, and what drivers really earn per hour.

* Per trip (rider and driver): the driver's share (fare share + boost + tip), Ride Pulse's
  commission, GST (collected for the government) and any discount Ride Pulse paid for.
* Per driver, over the last days: gross earnings, commission paid, an estimate of running costs
  (fuel and upkeep per km, including the empty drive to each pickup), hours online, and the
  real hourly figure after costs.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.core.conf import running_cost_per_km

from .models import Trip, TripStatus

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT)


def trip_split(trip: Trip) -> dict:
    """Who gets what from this trip's fare."""
    fare = trip.final_fare
    tip = trip.tip_amount or ZERO
    driver = fare.driver_earning + tip
    paid = fare.total + tip

    # Platform keeps commission + fees − discount; GST is collected for the government.
    def part(key: str, label: str, amount: Decimal) -> dict:
        return {"key": key, "label": label, "amount": _q(amount)}

    parts = [
        part("driver", "Your driver", driver),
        part("platform", "Ride Pulse commission", fare.platform_commission),
    ]
    for line in fare.lines:  # booking fee, airport fee: each with its own label
        if line.kind == "FEE" and line.amount:
            parts.append(part("fees", line.label, line.amount))
    if fare.discount:
        parts.append(part("discount", "Your discount (paid by Ride Pulse)", -fare.discount))
    parts.append(part("gst", "GST (to the government)", fare.gst))
    before_tax = fare.total - fare.gst
    return {
        "paid": _q(paid),
        "parts": parts,
        "driver_percent": round(driver / (before_tax + tip) * 100) if before_tax else 0,
        "tip": _q(tip),
    }


def _online_hours(driver, since: datetime, until: datetime) -> Decimal:
    from apps.drivers.models import DriverSession

    seconds = 0.0
    for start, end in DriverSession.objects.filter(driver=driver, started_at__lt=until).values_list(
        "started_at", "ended_at"
    ):
        end = end or until
        if end <= since:
            continue
        seconds += (min(end, until) - max(start, since)).total_seconds()
    return Decimal(seconds / 3600).quantize(Decimal("0.1"))


def driver_summary(driver, *, days: int = 7, now: datetime | None = None) -> dict:
    """The driver's real earnings over the last ``days``."""
    from .models import TripOffer

    now = now or timezone.now()
    since = now - timedelta(days=days)
    trips = Trip.objects.filter(
        driver=driver, status=TripStatus.COMPLETED, completed_at__gte=since
    ).select_related("ride_type")
    totals = trips.aggregate(
        fares=Sum("fare_total", default=ZERO),
        earnings=Sum("driver_earning", default=ZERO),
        tips=Sum("tip_amount", default=ZERO),
        commission=Sum("platform_commission", default=ZERO),
        km=Sum("actual_distance_km", default=ZERO),
    )
    pickup_km = TripOffer.objects.filter(
        trip__in=trips, driver=driver, status="ACCEPTED"
    ).aggregate(km=Sum("distance_km", default=ZERO))["km"]
    code = trips.first().ride_type.code if trips.exists() else "MINI"
    running_km = Decimal(totals["km"]) + Decimal(pickup_km)
    costs = _q(running_km * running_cost_per_km(code))
    gross = _q(totals["earnings"] + totals["tips"])
    net = gross - costs
    hours = _online_hours(driver, since, now)
    return {
        "days": days,
        "trips": trips.count(),
        "fares_collected": _q(totals["fares"]),
        "gross_earnings": gross,
        "commission_paid": _q(totals["commission"]),
        "running_km": running_km.quantize(Decimal("0.1")),
        "running_costs": costs,
        "running_cost_per_km": running_cost_per_km(code),
        "net_earnings": _q(net),
        "online_hours": hours,
        "net_per_hour": _q(net / hours) if hours else ZERO,
        "gross_per_hour": _q(gross / hours) if hours else ZERO,
        "commission_percent": (
            round(totals["commission"] / (totals["earnings"] + totals["commission"]) * 100)
            if totals["earnings"] + totals["commission"]
            else 0
        ),
    }
