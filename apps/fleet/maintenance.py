"""Vehicle upkeep: service intervals by distance, and insurance, permit and fitness expiry.

* The odometer is the reading when the vehicle joined plus every completed trip's distance.
* A service is due every ``SERVICE_INTERVAL_KM`` (by vehicle type); drivers and fleet owners are
  warned ``SERVICE_WARN_KM`` before, and logging a service resets the count.
* Insurance, permit and fitness certificates warn ``DOCUMENT_WARN_DAYS`` ahead. An expired
  insurance stops the driver going online (riding uninsured is illegal); the others warn.
"""

from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers.models import Vehicle
from apps.notifications.models import Level, Notification
from apps.notifications.services import notify
from apps.rides.models import Trip, TripStatus

from .models import ServiceRecord

DOCUMENTS = {
    "insurance_expires_on": "Insurance",
    "permit_expires_on": "Permit",
    "fitness_expires_on": "Fitness certificate",
}


def _conf(key):
    return settings.RIDE_PULSE[key]


def odometer(vehicle: Vehicle) -> int:
    driven = Trip.objects.filter(vehicle=vehicle, status=TripStatus.COMPLETED).aggregate(
        km=Sum("actual_distance_km")
    )["km"]
    return vehicle.odometer_base_km + int(driven or 0)


def interval_km(vehicle: Vehicle) -> int:
    return _conf("SERVICE_INTERVAL_KM").get(vehicle.ride_type.code, 10000)


def vehicle_health(vehicle: Vehicle, *, now: datetime | None = None, km: int | None = None) -> dict:
    today = timezone.localdate(now or timezone.now())
    km = odometer(vehicle) if km is None else km
    since = km - vehicle.last_service_km
    interval = interval_km(vehicle)
    left = interval - since
    service = "OVERDUE" if left <= 0 else "DUE_SOON" if left <= _conf("SERVICE_WARN_KM") else "OK"
    documents = []
    for field, label in DOCUMENTS.items():
        expires: date | None = getattr(vehicle, field)
        if expires is None:
            continue
        days = (expires - today).days
        documents.append(
            {
                "document": label,
                "expires_on": expires.isoformat(),
                "days_left": days,
                "status": "EXPIRED"
                if days < 0
                else "EXPIRING"
                if days <= _conf("DOCUMENT_WARN_DAYS")
                else "OK",
            }
        )
    worst = [service] + [d["status"] for d in documents]
    return {
        "id": vehicle.pk,
        "registration": vehicle.registration_number,
        "name": f"{vehicle.make} {vehicle.model}",
        "ride_type": vehicle.ride_type.code,
        "fuel_type": vehicle.fuel_type,
        "driver": vehicle.driver.name if vehicle.driver_id else None,
        "odometer_km": km,
        "km_since_service": since,
        "service_interval_km": interval,
        "service_due_in_km": left,
        "service": service,
        "documents": documents,
        "battery_percent": vehicle.battery_percent,
        "status": "ACTION"
        if {"OVERDUE", "EXPIRED"} & set(worst)
        else "SOON"
        if {"DUE_SOON", "EXPIRING"} & set(worst)
        else "OK",
    }


def record_service(
    vehicle: Vehicle,
    *,
    user,
    odometer_km: int | None = None,
    workshop: str = "",
    notes: str = "",
    serviced_on: date | None = None,
) -> ServiceRecord:
    current = odometer(vehicle)
    reading = odometer_km if odometer_km is not None else current
    if reading < vehicle.last_service_km:
        raise BusinessRuleViolation("That reading is below the last service.", field="odometer_km")
    if reading > current + 2000:
        raise BusinessRuleViolation(
            "That reading is far above the trips we've seen.", field="odometer_km"
        )
    record = ServiceRecord.objects.create(
        vehicle=vehicle,
        odometer_km=reading,
        serviced_on=serviced_on or timezone.localdate(),
        workshop=workshop[:120],
        notes=notes[:255],
        recorded_by=user,
    )
    # Keep the odometer honest if the owner's reading is ahead of trip distances.
    Vehicle.objects.filter(pk=vehicle.pk).update(
        last_service_km=reading,
        odometer_base_km=vehicle.odometer_base_km + max(0, reading - current),
    )
    return record


def _warned_recently(user, title: str, now: datetime) -> bool:
    return Notification.objects.filter(
        user=user, title=title, created_at__gte=now - timedelta(days=7)
    ).exists()


def sweep(*, now: datetime | None = None) -> dict:
    """Daily: warn drivers (and their fleet owner) about service and document deadlines."""
    now = now or timezone.now()
    distances = dict(
        Trip.objects.filter(status=TripStatus.COMPLETED, vehicle__isnull=False)
        .values_list("vehicle_id")
        .annotate(km=Sum("actual_distance_km"))
        .values_list("vehicle_id", "km")
    )
    warned = 0
    vehicles = Vehicle.objects.filter(is_active=True).select_related(
        "ride_type", "driver__user", "owner__user"
    )
    for vehicle in vehicles:
        health = vehicle_health(
            vehicle, now=now, km=vehicle.odometer_base_km + int(distances.get(vehicle.pk) or 0)
        )
        if health["status"] == "OK":
            continue
        problems = []
        if health["service"] != "OK":
            problems.append(
                "service overdue"
                if health["service"] == "OVERDUE"
                else f"service due in {health['service_due_in_km']} km"
            )
        problems += [
            f"{d['document'].lower()} {'expired' if d['status'] == 'EXPIRED' else 'expires'} "
            f"{d['expires_on']}"
            for d in health["documents"]
            if d["status"] != "OK"
        ]
        title = f"{vehicle.registration_number}: {', '.join(problems)}"[:160]
        level = Level.DANGER if health["status"] == "ACTION" else Level.WARNING
        for user in filter(
            None,
            [
                vehicle.driver.user if vehicle.driver_id else None,
                vehicle.owner.user if vehicle.owner_id else None,
            ],
        ):
            if not _warned_recently(user, title, now):
                notify(user, title, "Open Vehicle care in the app to log a service.", level=level)
                warned += 1
    return {"warned": warned}


def fleet_health(*, city_id: int | None = None) -> dict:
    """Ops: vehicles needing attention, by status."""
    distances = dict(
        Trip.objects.filter(status=TripStatus.COMPLETED, vehicle__isnull=False)
        .values_list("vehicle_id")
        .annotate(km=Sum("actual_distance_km"))
        .values_list("vehicle_id", "km")
    )
    vehicles = Vehicle.objects.filter(is_active=True).select_related("ride_type", "driver__user")
    if city_id:
        vehicles = vehicles.filter(driver__city_id=city_id)
    rows = [
        vehicle_health(v, km=v.odometer_base_km + int(distances.get(v.pk) or 0)) for v in vehicles
    ]
    attention = [r for r in rows if r["status"] != "OK"]
    attention.sort(key=lambda r: (r["status"] != "ACTION", r["service_due_in_km"]))
    return {
        "vehicles": len(rows),
        "action": sum(r["status"] == "ACTION" for r in rows),
        "soon": sum(r["status"] == "SOON" for r in rows),
        "service_overdue": sum(r["service"] == "OVERDUE" for r in rows),
        "insurance_expired": sum(
            any(d["document"] == "Insurance" and d["status"] == "EXPIRED" for d in r["documents"])
            for r in rows
        ),
        "attention": attention[:200],
    }
