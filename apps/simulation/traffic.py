"""The simulator's "real world" traffic: how long a trip really takes.

The app's own estimate (``geo.routing``) knows only distance and the hour of the day. Real Indian
traffic has more structure, and this module is the hidden ground truth the simulator drives by:

* metros are slower than tier-1 cities, which are slower than smaller ones;
* the city centre is congested; airport runs use faster arterial roads;
* weekday evening peaks are worse than morning ones, and weekends are lighter;
* rain slows everyone (more the heavier it is);
* bikes filter through traffic, autos a little, big SUVs are slightly slower;
* and every trip has some luck in it.

Nothing in the app reads this module: an ETA model has to learn these effects from trip
history, exactly as a real platform learns them from real trips.
"""

import math
import random
from datetime import datetime

from django.utils import timezone

from apps.geo.distance import haversine_km

METROS = {"chennai", "bengaluru"}
TIER_ONE = {
    "coimbatore",
    "kochi",
    "visakhapatnam",
    "thiruvananthapuram",
    "vijayawada",
    "madurai",
    "mysuru",
    "mangaluru",
    "kozhikode",
    "tiruchirappalli",
    "tirupati",
    "hubballi-dharwad",
}
VEHICLE = {
    "BIKE": 0.8,
    "PARCEL": 0.8,
    "AUTO": 0.94,
    "MINI": 1.0,
    "SHARE": 1.06,
    "SEDAN": 1.0,
    "SUV": 1.05,
}


def city_factor(slug: str) -> float:
    return 1.22 if slug in METROS else 1.08 if slug in TIER_ONE else 0.92


def time_factor(at: datetime) -> float:
    local = timezone.localtime(at)
    hour, weekend = local.hour, local.weekday() >= 5
    if weekend:
        return 0.95 if 11 <= hour <= 21 else 0.82
    if 17 <= hour <= 20:  # the evening rush is the worst of the day
        return 1.3
    if 8 <= hour <= 10:
        return 1.12
    if hour >= 23 or hour <= 5:
        return 0.85
    return 1.0


def rain_factor(city, at: datetime) -> float:
    """Rain at that hour: the recorded weather when there is some (the same history the
    platform keeps), otherwise the seasonal simulation."""
    from datetime import timedelta

    from apps.intelligence.context import _simulate
    from apps.intelligence.models import WeatherReading

    hour = at.replace(minute=0, second=0, microsecond=0)
    reading = (
        WeatherReading.objects.filter(
            city=city,
            observed_at__gte=hour - timedelta(minutes=30),
            observed_at__lt=hour + timedelta(minutes=90),
        )
        .values_list("rain_mm", flat=True)
        .first()
    )
    rain = float(reading) if reading is not None else float(_simulate(city, at)["rain_mm"])
    return 1 + min(0.35, 0.045 * rain)


def centre_factor(city, lat: float, lng: float) -> float:
    return 1.12 if haversine_km(lat, lng, city.center_lat, city.center_lng) < 3.0 else 1.0


def true_minutes(trip, at: datetime, rng: random.Random) -> float:
    """How long this trip really takes, starting at ``at``."""
    city = trip.city
    factor = (
        city_factor(city.slug)
        * time_factor(at)
        * rain_factor(city, at)
        * max(
            centre_factor(city, trip.pickup_lat, trip.pickup_lng),
            centre_factor(city, trip.dropoff_lat, trip.dropoff_lng),
        )
        * VEHICLE.get(trip.ride_type.code, 1.0)
        * (
            0.88
            if (trip.pickup_zone_id and trip.pickup_zone.is_airport)
            or (trip.dropoff_zone_id and trip.dropoff_zone.is_airport)
            else 1.0
        )
    )
    luck = math.exp(rng.gauss(0, 0.08))
    return max(3.0, float(trip.estimated_duration_min) * factor * luck)
