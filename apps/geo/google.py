"""Google Maps Platform: road routes and traffic-aware ETAs from the Routes API.

Enabled by setting ``GOOGLE_MAPS_API_KEY`` (a server key, restricted to the Routes API and your
server's IP). Without a key, or if Google is slow or failing, callers fall back to the built-in
estimate, so the platform never depends on Google being reachable.

Calls are cached for a few minutes per (origin, destination) rounded to ~11 m, so a rider
flicking between ride types costs one API call, not five.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
TIMEOUT_SECONDS = 2.5
CACHE_SECONDS = 300


class GoogleMapsError(Exception):
    pass


@dataclass(frozen=True)
class GoogleRoute:
    distance_km: Decimal
    duration_minutes: Decimal
    polyline: str


def server_key() -> str:
    return getattr(settings, "GOOGLE_MAPS_API_KEY", "") or ""


def enabled() -> bool:
    return bool(server_key())


def _cache_key(origin, destination, traffic: bool) -> str:
    o = f"{origin[0]:.4f},{origin[1]:.4f}"
    d = f"{destination[0]:.4f},{destination[1]:.4f}"
    return f"gmaps:route:{o}:{d}:{int(traffic)}"


def _waypoint(lat: float, lng: float) -> dict:
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def _post(body: dict) -> dict:
    request = urllib.request.Request(
        ROUTES_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": server_key(),
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        raise GoogleMapsError(f"Routes API returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GoogleMapsError(f"Routes API unreachable: {exc}") from exc


def compute_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    departure: datetime | None = None,
    traffic: bool | None = None,
) -> GoogleRoute:
    """Driving route between two points. Raises GoogleMapsError on any failure."""
    if not enabled():
        raise GoogleMapsError("GOOGLE_MAPS_API_KEY is not set")
    traffic = getattr(settings, "GOOGLE_ROUTES_TRAFFIC_AWARE", True) if traffic is None else traffic
    key = _cache_key(origin, destination, traffic)
    cached = cache.get(key)
    if cached:
        return GoogleRoute(Decimal(cached[0]), Decimal(cached[1]), cached[2])

    body = {
        "origin": _waypoint(*origin),
        "destination": _waypoint(*destination),
        "travelMode": "DRIVE",
        # Traffic-aware routing is billed as the "Pro" SKU; unaware routing as "Essentials".
        "routingPreference": "TRAFFIC_AWARE" if traffic else "TRAFFIC_UNAWARE",
        "languageCode": "en-IN",
        "units": "METRIC",
    }
    now = timezone.now()
    if traffic and departure and departure > now:
        body["departureTime"] = departure.isoformat()
    data = _post(body)
    routes = data.get("routes") or []
    if not routes:
        raise GoogleMapsError("Routes API found no route")
    route = routes[0]
    q = Decimal("0.01")
    distance_km = (Decimal(route.get("distanceMeters", 0)) / 1000).quantize(q, ROUND_HALF_UP)
    seconds = Decimal(str(route.get("duration", "0s")).rstrip("s") or 0)
    duration_min = max(Decimal(1), (seconds / 60)).quantize(q, ROUND_HALF_UP)
    polyline = (route.get("polyline") or {}).get("encodedPolyline", "")
    cache.set(key, (str(distance_km), str(duration_min), polyline), CACHE_SECONDS)
    return GoogleRoute(distance_km, duration_min, polyline)


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Google's encoded polyline format -> [(lat, lng), ...]."""
    points, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for coordinate in (0, 1):
            shift, result = 0, 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coordinate == 0:
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def encode_polyline(points: list[tuple[float, float]]) -> str:
    """[(lat, lng), ...] -> Google's encoded polyline format (inverse of ``decode_polyline``)."""
    out, prev_lat, prev_lng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)
