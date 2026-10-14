"""City service catalogue: don't offer a ride type in a city nobody there can drive.

A ride type is served by approved drivers whose active vehicle is that type (a Parcel by Bike
drivers who accept parcels). When a city has none, its fare rule is paused automatically, so the
type disappears from the booking screen there; it comes back as soon as a driver is approved.
Rules that operations switched off by hand are never touched.
"""

from django.db.models import Count, Q

from apps.drivers.models import DriverProfile, OnboardingStatus

from .models import FareRule


def drivers_by_city_and_vehicle() -> dict[tuple[int, int], dict]:
    rows = (
        DriverProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED, vehicles__is_active=True
        )
        .values("city_id", "vehicles__ride_type_id")
        .annotate(n=Count("id"), parcels=Count("id", filter=Q(accepts_parcels=True)))
    )
    return {(r["city_id"], r["vehicles__ride_type_id"]): r for r in rows}


def sync(city_id: int | None = None) -> dict:
    """Pause or resume fare rules by driver coverage. Returns what changed."""
    supply = drivers_by_city_and_vehicle()
    rules = FareRule.objects.select_related("ride_type", "city")
    if city_id is not None:
        rules = rules.filter(city_id=city_id)
    paused, resumed = [], []
    for rule in rules:
        ride_type = rule.ride_type
        row = supply.get((rule.city_id, ride_type.vehicle_type_id or ride_type.pk), {})
        drivers = row.get("parcels", 0) if ride_type.service == "PARCEL" else row.get("n", 0)
        label = f"{rule.city.name} · {ride_type.name}"
        if drivers == 0 and rule.is_active:
            rule.is_active, rule.auto_paused = False, True
            rule.save(update_fields=["is_active", "auto_paused", "updated_at"])
            paused.append(label)
        elif drivers > 0 and rule.auto_paused:
            rule.is_active, rule.auto_paused = True, False
            rule.save(update_fields=["is_active", "auto_paused", "updated_at"])
            resumed.append(label)
    return {"paused": paused, "resumed": resumed}
