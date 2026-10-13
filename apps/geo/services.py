from apps.core.exceptions import BusinessRuleViolation

from .distance import haversine_km
from .models import City, Landmark, Zone

ZONE_SNAP_KM = 6.0  # points outside every zone snap to the nearest one within this distance


def city_for_point(lat: float, lng: float) -> City | None:
    cities = [c for c in City.objects.filter(is_active=True) if c.contains(lat, lng)]
    return min(
        cities, key=lambda c: haversine_km(c.center_lat, c.center_lng, lat, lng), default=None
    )


def require_city(lat: float, lng: float) -> City:
    city = city_for_point(lat, lng)
    if city is None:
        raise BusinessRuleViolation(
            "Ride Pulse doesn't operate at this location yet.", field="pickup"
        )
    return city


def zone_for_point(
    city: City, lat: float, lng: float, zones: list[Zone] | None = None
) -> Zone | None:
    """The zone containing the point; otherwise the nearest zone within ``ZONE_SNAP_KM``."""
    zones = zones if zones is not None else list(city.zones.all())
    if not zones:
        return None
    nearest = min(zones, key=lambda z: z.distance_km(lat, lng))
    distance = nearest.distance_km(lat, lng)
    return nearest if distance <= max(nearest.radius_km, ZONE_SNAP_KM) else None


NEAR_LANDMARK_KM = 0.6


def search_places(query: str, *, city: City | None = None, limit: int = 8) -> list[dict]:
    """Suggestions for the "Where to?" box: landmarks first, then neighbourhoods."""
    query = query.strip()
    if len(query) < 2:
        return []
    landmarks = Landmark.objects.filter(name__icontains=query).select_related("city")
    zones = Zone.objects.filter(name__icontains=query).select_related("city")
    if city is not None:
        landmarks, zones = landmarks.filter(city=city), zones.filter(city=city)
    results = [
        {
            "name": place.name,
            "address": f"{place.address}, {place.city.name}" if place.address else place.city.name,
            "category": place.get_category_display(),
            "lat": place.lat,
            "lng": place.lng,
            "city": place.city.slug,
        }
        for place in landmarks[:limit]
    ]
    results += [
        {
            "name": z.name,
            "address": z.city.name,
            "category": "Airport" if z.is_airport else "Area",
            "lat": z.center_lat,
            "lng": z.center_lng,
            "city": z.city.slug,
        }
        for z in zones[: max(limit - len(results), 0)]
    ]
    return results


def describe_point(lat: float, lng: float) -> str:
    """A human label for a dropped pin: "Near Marina Beach", or the neighbourhood."""
    city = city_for_point(lat, lng)
    if city is None:
        return "Pinned location"
    nearest = min(
        city.landmarks.all(), key=lambda p: haversine_km(p.lat, p.lng, lat, lng), default=None
    )
    if nearest and haversine_km(nearest.lat, nearest.lng, lat, lng) <= NEAR_LANDMARK_KM:
        return f"Near {nearest.name}"
    zone = zone_for_point(city, lat, lng)
    return f"{zone.name}, {city.name}" if zone else city.name
