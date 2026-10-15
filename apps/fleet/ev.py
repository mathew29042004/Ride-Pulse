"""Electric vehicles: range-aware dispatch, battery tracking and nearby chargers.

* The driver app reports the battery level (the simulator drains it with every trip). Range left
  = battery x the vehicle's full range (``EV_RANGE_KM``).
* Dispatch only offers an EV driver a trip they can finish (pickup + trip distance) while
  keeping ``EV_RESERVE_KM`` to reach a charger, so no rider is left with a flat car.
* Below 20% the driver is told where the nearest suitable chargers are.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers.models import DriverProfile, FuelType, Vehicle
from apps.geo.distance import haversine_km
from apps.notifications.models import Level, Notification
from apps.notifications.services import notify

from .models import ChargingStation

LOW_BATTERY = 20
TWO_WHEELERS = {"BIKE"}


def full_range_km(vehicle: Vehicle) -> float:
    return float(settings.RIDE_PULSE["EV_RANGE_KM"].get(vehicle.ride_type.code, 200))


def range_left_km(vehicle: Vehicle) -> float | None:
    if vehicle is None or vehicle.fuel_type != FuelType.EV or vehicle.battery_percent is None:
        return None
    return full_range_km(vehicle) * vehicle.battery_percent / 100


def can_take(vehicle: Vehicle | None, trip, *, pickup_km: float = 0.0) -> bool:
    left = range_left_km(vehicle)
    if left is None:
        return True  # not an EV, or the battery level is unknown
    needed = float(pickup_km or 0) + float(trip.estimated_distance_km or 0)
    return left - needed >= settings.RIDE_PULSE["EV_RESERVE_KM"]


def set_battery(driver: DriverProfile, percent: int, *, now: datetime | None = None) -> Vehicle:
    vehicle = driver.active_vehicle
    if vehicle is None or vehicle.fuel_type != FuelType.EV:
        raise BusinessRuleViolation("Your vehicle isn't electric.")
    if not 0 <= percent <= 100:
        raise BusinessRuleViolation("Battery is 0-100%.", field="percent")
    now = now or timezone.now()
    Vehicle.objects.filter(pk=vehicle.pk).update(battery_percent=percent, battery_updated_at=now)
    vehicle.battery_percent, vehicle.battery_updated_at = percent, now
    _maybe_warn(driver, vehicle, now)
    return vehicle


def drain(vehicle: Vehicle, km: float, *, now: datetime | None = None) -> None:
    """A trip used ``km`` of range (the simulator, or a car without live battery data)."""
    if vehicle.fuel_type != FuelType.EV or vehicle.battery_percent is None:
        return
    used = round(100 * km / full_range_km(vehicle))
    percent = max(0, vehicle.battery_percent - max(1, used))
    Vehicle.objects.filter(pk=vehicle.pk).update(
        battery_percent=percent, battery_updated_at=now or timezone.now()
    )
    vehicle.battery_percent = percent
    if vehicle.driver_id:
        _maybe_warn(vehicle.driver, vehicle, now or timezone.now())


def _maybe_warn(driver: DriverProfile, vehicle: Vehicle, now: datetime) -> None:
    if vehicle.battery_percent is None or vehicle.battery_percent >= LOW_BATTERY:
        return
    title = f"Battery at {vehicle.battery_percent}%: time to charge"
    recent = Notification.objects.filter(
        user=driver.user, title__startswith="Battery at", created_at__gte=now - timedelta(hours=1)
    )
    if recent.exists():
        return
    nearest = chargers_near(driver, limit=1)
    body = (
        f"Nearest: {nearest[0]['name']}, {nearest[0]['distance_km']} km away."
        if nearest
        else "Find a charger in the app."
    )
    notify(
        driver.user,
        title,
        body + " You'll only get trips your range can finish.",
        level=Level.WARNING,
    )


def chargers_near(driver: DriverProfile, *, limit: int = 5) -> list[dict]:
    if driver.current_lat is None:
        return []
    vehicle = driver.active_vehicle
    stations = ChargingStation.objects.filter(city_id=driver.city_id)
    if vehicle is not None:
        stations = (
            stations.filter(two_wheeler=True)
            if vehicle.ride_type.code in TWO_WHEELERS
            else stations.filter(four_wheeler=True)
        )
    rows = []
    for s in stations:
        rows.append(
            {
                "id": s.pk,
                "name": s.name,
                "operator": s.operator,
                "lat": s.lat,
                "lng": s.lng,
                "power_kw": s.power_kw,
                "connectors": s.connectors,
                "price_per_kwh": str(s.price_per_kwh),
                "distance_km": round(
                    haversine_km(driver.current_lat, driver.current_lng, s.lat, s.lng), 1
                ),
            }
        )
    rows.sort(key=lambda r: r["distance_km"])
    return rows[:limit]


def my_ev(driver: DriverProfile) -> dict | None:
    vehicle = driver.active_vehicle
    if vehicle is None or vehicle.fuel_type != FuelType.EV:
        return None
    left = range_left_km(vehicle)
    return {
        "battery_percent": vehicle.battery_percent,
        "range_left_km": round(left) if left is not None else None,
        "full_range_km": round(full_range_km(vehicle)),
        "reserve_km": settings.RIDE_PULSE["EV_RESERVE_KM"],
        "low": vehicle.battery_percent is not None and vehicle.battery_percent < LOW_BATTERY,
        "chargers": chargers_near(driver, limit=3),
    }


def overview() -> dict:
    """Ops: the electric fleet and the charging network."""
    evs = Vehicle.objects.filter(fuel_type=FuelType.EV, is_active=True)
    by_city = dict(
        ChargingStation.objects.values_list("city__name")
        .annotate(n=Count("pk"))
        .values_list("city__name", "n")
    )
    low = evs.filter(battery_percent__lt=LOW_BATTERY).count()
    return {
        "ev_vehicles": evs.count(),
        "share_percent": round(
            100 * evs.count() / max(1, Vehicle.objects.filter(is_active=True).count()), 1
        ),
        "low_battery": low,
        "chargers": ChargingStation.objects.count(),
        "chargers_by_city": by_city,
    }
