"""Spherical geometry helpers (no PostGIS needed at city scale)."""

import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE_LAT = 111.32


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) of a box that contains the circle.

    Used as an index-friendly pre-filter before the exact haversine distance is computed.
    """
    d_lat = radius_km / KM_PER_DEGREE_LAT
    d_lng = radius_km / (KM_PER_DEGREE_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return lat - d_lat, lat + d_lat, lng - d_lng, lng + d_lng


def offset(lat: float, lng: float, km_north: float, km_east: float) -> tuple[float, float]:
    new_lat = lat + km_north / KM_PER_DEGREE_LAT
    new_lng = lng + km_east / (KM_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return new_lat, new_lng


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lng2 - lng1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def move_towards(
    lat: float, lng: float, target_lat: float, target_lng: float, step_km: float
) -> tuple[float, float, bool]:
    """Advance up to ``step_km`` towards the target. Returns (lat, lng, arrived)."""
    remaining = haversine_km(lat, lng, target_lat, target_lng)
    if remaining <= step_km or remaining == 0:
        return target_lat, target_lng, True
    fraction = step_km / remaining
    return lat + (target_lat - lat) * fraction, lng + (target_lng - lng) * fraction, False


def arc(
    start: tuple[float, float], end: tuple[float, float], segments: int = 32
) -> list[tuple[float, float]]:
    """The gentle curve the apps draw when no road route is known (mirrors ``arc`` in the
    frontend's map/shared.ts), so simulated cars drive along the line riders see."""
    (lat1, lng1), (lat2, lng2) = start, end
    ctrl = ((lat1 + lat2) / 2 - (lng2 - lng1) * 0.18, (lng1 + lng2) / 2 + (lat2 - lat1) * 0.18)
    points = []
    for i in range(segments + 1):
        t = i / segments
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        points.append((a * lat1 + b * ctrl[0] + c * lat2, a * lng1 + b * ctrl[1] + c * lng2))
    return points


def move_along(
    path: list[tuple[float, float]], lat: float, lng: float, step_km: float
) -> tuple[float, float, bool]:
    """Advance up to ``step_km`` along ``path`` from the point on it nearest to (lat, lng).

    Stateless, so a restarted simulator picks up where its cars are. Returns (lat, lng, arrived).
    """
    if len(path) < 2:
        return move_towards(lat, lng, *path[-1], step_km)
    k = math.cos(math.radians(lat))  # flatten longitude so the projection is roughly metric
    best = (math.inf, 0, 0.0)
    for i in range(len(path) - 1):
        (ay, ax), (by, bx) = path[i], path[i + 1]
        dx, dy = (bx - ax) * k, by - ay
        px, py = (lng - ax) * k, lat - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, (px * dx + py * dy) / length2))
        dist2 = (px - t * dx) ** 2 + (py - t * dy) ** 2
        if dist2 < best[0]:
            best = (dist2, i, t)
    _, i, t = best
    (ay, ax), (by, bx) = path[i], path[i + 1]
    current = (ay + (by - ay) * t, ax + (bx - ax) * t)
    left = step_km
    while i < len(path) - 1:
        target = path[i + 1]
        segment = haversine_km(*current, *target)
        if segment > left:
            fraction = left / segment
            return (
                current[0] + (target[0] - current[0]) * fraction,
                current[1] + (target[1] - current[1]) * fraction,
                False,
            )
        left -= segment
        current = target
        i += 1
    return current[0], current[1], True
