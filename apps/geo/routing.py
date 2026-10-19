"""Route estimates.

With ``GOOGLE_MAPS_API_KEY`` set, trip routes come from the Google Routes API (real roads,
live traffic, and a polyline to draw). Otherwise, or if Google fails, a built-in estimate is
used: great-circle distance times a detour factor (1.3 is typical for Indian city grids), with
travel time from an hour-of-day speed profile, so a 10 km ride at 18:30 takes far longer than
the same ride at 23:00.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from django.utils import timezone

from apps.core.conf import road_distance_factor

from . import google
from .distance import haversine_km

logger = logging.getLogger(__name__)

# Average city speed (km/h) by local hour of day.
SPEED_PROFILE_KMH: dict[int, float] = {
    **dict.fromkeys(range(6), 32.0),
    **dict.fromkeys(range(6, 8), 26.0),
    **dict.fromkeys(range(8, 11), 17.0),  # morning peak
    **dict.fromkeys(range(11, 17), 23.0),
    **dict.fromkeys(range(17, 21), 16.0),  # evening peak
    **dict.fromkeys(range(21, 24), 27.0),
}
MIN_TRIP_MINUTES = 1.0
# Time allowed for a stop on the way (dropping someone off, picking something up).
STOP_WAIT_MINUTES = Decimal(3)


@dataclass(frozen=True)
class RouteEstimate:
    distance_km: Decimal
    duration_minutes: Decimal
    polyline: str = ""  # Google encoded polyline, when a real route is known
    source: str = "estimate"  # "google" or "estimate"


def average_speed_kmh(at: datetime) -> float:
    return SPEED_PROFILE_KMH[timezone.localtime(at).hour]


def is_peak_hour(at: datetime) -> bool:
    return average_speed_kmh(at) <= 17.0


def road_distance_km(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    return haversine_km(from_lat, from_lng, to_lat, to_lng) * float(road_distance_factor())


def travel_minutes(distance_km: float, at: datetime) -> float:
    return max(distance_km / average_speed_kmh(at) * 60, MIN_TRIP_MINUTES)


def _maps_down() -> bool:
    from apps.reliability.fallbacks import SIMPLE_ROUTES, active

    return SIMPLE_ROUTES in active()


def estimate_route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float, at: datetime
) -> RouteEstimate:
    if google.enabled() and not _maps_down():
        try:
            route = google.compute_route((from_lat, from_lng), (to_lat, to_lng), departure=at)
            return RouteEstimate(
                route.distance_km, route.duration_minutes, route.polyline, "google"
            )
        except google.GoogleMapsError as exc:
            logger.warning("Falling back to estimated route: %s", exc)
    return heuristic_route(from_lat, from_lng, to_lat, to_lng, at)


def heuristic_route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float, at: datetime
) -> RouteEstimate:
    distance = road_distance_km(from_lat, from_lng, to_lat, to_lng)
    minutes = travel_minutes(distance, at)
    q = Decimal("0.01")
    return RouteEstimate(
        distance_km=Decimal(str(distance)).quantize(q, ROUND_HALF_UP),
        duration_minutes=Decimal(str(minutes)).quantize(q, ROUND_HALF_UP),
    )


def eta_minutes(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float, at: datetime
) -> float:
    return travel_minutes(road_distance_km(from_lat, from_lng, to_lat, to_lng), at)


def estimate_route_via(points: list[tuple[float, float]], at: datetime) -> RouteEstimate:
    """A route through several points (pickup, stops, drop): the legs added up, plus a few
    minutes per stop. Road polylines are joined when every leg has one."""
    if len(points) == 2:
        return estimate_route(*points[0], *points[1], at)
    legs = [estimate_route(*a, *b, at) for a, b in pairwise(points)]
    stops = len(points) - 2
    polyline = ""
    if all(leg.polyline for leg in legs):
        path = []
        for leg in legs:
            decoded = google.decode_polyline(leg.polyline)
            path.extend(decoded[1:] if path else decoded)
        polyline = google.encode_polyline(path)
    return RouteEstimate(
        distance_km=sum((leg.distance_km for leg in legs), Decimal(0)),
        duration_minutes=sum((leg.duration_minutes for leg in legs), Decimal(0))
        + STOP_WAIT_MINUTES * stops,
        polyline=polyline,
        source="google" if all(leg.source == "google" for leg in legs) else "estimate",
    )
