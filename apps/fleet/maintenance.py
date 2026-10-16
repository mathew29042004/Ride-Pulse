"""Vehicle upkeep: service intervals by distance, and insurance, permit and fitness expiry.

* The odometer is the reading when the vehicle joined plus every completed trip's distance.
* A service is due every ``SERVICE_INTERVAL_KM`` (by vehicle type); drivers and fleet owners are
  warned ``SERVICE_WARN_KM`` before, and logging a service resets the count.
* Insurance, permit and fitness certificates warn ``DOCUMENT_WARN_DAYS`` ahead. An expired
  insurance stops the driver going online (riding uninsured is illegal); the others warn.
* **Condition**: a vehicle is on the road, in the workshop, or off the road (unsafe). Only a
  vehicle on the road can take rides. A critical fault (a breakdown, an accident, failed brakes,
  tyres, lights or belts on the daily check) takes it off the road at once; logging the repair
  puts it back.
* **Daily check**: before the first ride of the day the driver ticks a walk-round checklist.
* **Issues** come from the driver, the daily check, riders (after a ride), the fleet owner or
  ops. A breakdown during a ride ends it at no charge to the rider, who gets a replacement.
* **Service records** keep the kind of work, parts, costs and the invoice number; the cost per
  km feeds the owner's and ops' view.

The overall ``state`` a person sees is the worst of: OFF_ROAD, IN_WORKSHOP, OVERDUE (service
or an expired document), DUE (service soon, a document expiring, or an open fault) and OK.
"""

from datetime import date, datetime, timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers.models import Vehicle, VehicleCondition
from apps.notifications.models import Level, Notification
from apps.notifications.services import notify
from apps.rides.models import Trip, TripStatus

from .models import (
    IssueKind,
    IssueSeverity,
    IssueSource,
    IssueStatus,
    ServiceKind,
    ServiceRecord,
    VehicleInspection,
    VehicleIssue,
)

CHECKLIST = {
    "brakes": "Brakes",
    "tyres": "Tyres (pressure and tread)",
    "lights": "Headlights, indicators, brake lights",
    "seatbelts": "Seat belts (every seat)",
    "horn": "Horn",
    "wipers": "Wipers and washer",
    "mirrors": "Mirrors",
    "first_aid": "First-aid kit",
    "extinguisher": "Fire extinguisher",
    "clean": "Clean inside",
}
# A failed critical item makes the vehicle unsafe: off the road until repaired.
CRITICAL_ITEMS = {
    "brakes": IssueKind.BRAKES,
    "tyres": IssueKind.TYRES,
    "lights": IssueKind.LIGHTS,
    "seatbelts": IssueKind.SEATBELTS,
}
GROUNDING_KINDS = {IssueKind.BREAKDOWN, IssueKind.ACCIDENT}
RIDER_KINDS = {IssueKind.AC, IssueKind.CLEANLINESS, IssueKind.SEATBELTS, IssueKind.OTHER}

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


def with_health_data(vehicles):
    """Prefetch what ``vehicle_health`` reads: open issues and the last week's daily checks."""
    from django.db.models import Prefetch

    week = timezone.localdate() - timedelta(days=7)
    return vehicles.prefetch_related(
        Prefetch("issues", queryset=VehicleIssue.objects.exclude(status=IssueStatus.RESOLVED)),
        Prefetch("inspections", queryset=VehicleInspection.objects.filter(inspected_on__gte=week)),
    )


def health_of(vehicle: Vehicle, **kwargs) -> dict:
    """``vehicle_health`` for one vehicle, fetched fresh."""
    vehicle = with_health_data(Vehicle.objects.select_related("ride_type", "driver__user")).get(
        pk=vehicle.pk
    )
    return vehicle_health(vehicle, **kwargs)


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
    open_issues = [
        {
            "id": i.pk,
            "kind": i.kind,
            "kind_label": i.get_kind_display(),
            "severity": i.severity,
            "source": i.source,
            "status": i.status,
            "description": i.description,
            "opened_at": i.opened_at.isoformat(),
        }
        for i in vehicle.issues.all()  # prefetched by callers with the open ones only
        if i.status != IssueStatus.RESOLVED
    ]
    checked_today = any(i.inspected_on == today and i.passed for i in vehicle.inspections.all())
    if vehicle.condition == VehicleCondition.OFF_ROAD:
        state = "OFF_ROAD"
    elif vehicle.condition == VehicleCondition.IN_WORKSHOP:
        state = "IN_WORKSHOP"
    elif {"OVERDUE", "EXPIRED"} & set(worst):
        state = "OVERDUE"
    elif {"DUE_SOON", "EXPIRING"} & set(worst) or open_issues:
        state = "DUE"
    else:
        state = "OK"
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
        "condition": vehicle.condition,
        "condition_note": vehicle.condition_note,
        "state": state,
        "open_issues": open_issues,
        "checked_today": checked_today,
        "status": "ACTION"
        if state in ("OFF_ROAD", "IN_WORKSHOP", "OVERDUE")
        else "SOON"
        if state == "DUE"
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
    kind: str = ServiceKind.ROUTINE,
    parts: list[dict] | None = None,
    labour_cost=0,
    invoice_number: str = "",
    resolves: list[int] | None = None,
    now: datetime | None = None,
) -> ServiceRecord:
    """Log a workshop visit. Repairs resolve the vehicle's open issues (or the ones given) and,
    with no critical fault left, put the vehicle back on the road."""
    from decimal import Decimal, InvalidOperation

    now = now or timezone.now()
    clean_parts = []
    for part in (parts or [])[:30]:
        name = str(part.get("name", "")).strip()[:80]
        try:
            cost = Decimal(str(part.get("cost") or 0)).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise BusinessRuleViolation(
                f"Check the cost of {name or 'a part'}.", field="parts"
            ) from None
        if not name or cost < 0:
            raise BusinessRuleViolation("Each part needs a name and a cost.", field="parts")
        clean_parts.append({"name": name, "cost": str(cost)})
    labour = Decimal(str(labour_cost or 0)).quantize(Decimal("0.01"))
    if labour < 0:
        raise BusinessRuleViolation("Labour can't be negative.", field="labour_cost")
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
        kind=kind,
        parts=clean_parts,
        parts_cost=sum((Decimal(p["cost"]) for p in clean_parts), Decimal(0)),
        labour_cost=labour,
        invoice_number=invoice_number[:40],
    )
    # Keep the odometer honest if the owner's reading is ahead of trip distances.
    Vehicle.objects.filter(pk=vehicle.pk).update(
        last_service_km=reading,
        odometer_base_km=vehicle.odometer_base_km + max(0, reading - current),
    )
    issues = vehicle.issues.exclude(status=IssueStatus.RESOLVED)
    if resolves is not None:
        issues = issues.filter(pk__in=resolves)
    elif kind == ServiceKind.ROUTINE:
        issues = issues.none()  # a routine service doesn't claim to fix reported faults
    issues.update(status=IssueStatus.RESOLVED, repair=record, resolved_at=now)
    _refresh_condition(
        vehicle, now=now, note=f"Back on the road after {record.get_kind_display().lower()}"
    )
    return record


# --- Condition, daily checks and issues ------------------------------------------------------


def _people(vehicle: Vehicle) -> list:
    return [
        u
        for u in (
            vehicle.driver.user if vehicle.driver_id else None,
            vehicle.owner.user if vehicle.owner_id else None,
        )
        if u is not None
    ]


def set_condition(vehicle: Vehicle, condition: str, *, note: str = "", now=None) -> Vehicle:
    if condition not in VehicleCondition.values:
        raise BusinessRuleViolation("Choose a valid condition.", field="condition")
    now = now or timezone.now()
    if (
        condition == VehicleCondition.ACTIVE
        and vehicle.issues.filter(severity=IssueSeverity.CRITICAL)
        .exclude(status=IssueStatus.RESOLVED)
        .exists()
    ):
        raise BusinessRuleViolation(
            "A critical fault is still open: log the repair first.", field="condition"
        )
    if vehicle.condition == condition:
        return vehicle
    Vehicle.objects.filter(pk=vehicle.pk).update(
        condition=condition, condition_note=note[:200], condition_since=now
    )
    vehicle.condition, vehicle.condition_note, vehicle.condition_since = condition, note[:200], now
    if condition != VehicleCondition.ACTIVE and vehicle.driver_id:
        _take_offline(vehicle.driver, now)
    label = VehicleCondition(condition).label.lower()
    for user in _people(vehicle):
        notify(
            user,
            f"{vehicle.registration_number} is {label}",
            note or "See Vehicle care in the app.",
            level=Level.SUCCESS if condition == VehicleCondition.ACTIVE else Level.WARNING,
        )
    return vehicle


def _refresh_condition(vehicle: Vehicle, *, now, note: str) -> None:
    vehicle.refresh_from_db(fields=["condition", "condition_note", "condition_since"])
    critical = vehicle.issues.filter(severity=IssueSeverity.CRITICAL).exclude(
        status=IssueStatus.RESOLVED
    )
    if vehicle.condition != VehicleCondition.ACTIVE and not critical.exists():
        set_condition(vehicle, VehicleCondition.ACTIVE, note=note, now=now)


def _take_offline(driver, now) -> None:
    from apps.drivers import services as drivers
    from apps.drivers.models import Availability

    driver.refresh_from_db(fields=["availability"])
    if driver.availability == Availability.ONLINE:
        drivers.go_offline(driver, now=now)


def report_issue(
    vehicle: Vehicle,
    *,
    user,
    source: str,
    kind: str,
    severity: str | None = None,
    description: str = "",
    trip=None,
    now: datetime | None = None,
) -> VehicleIssue:
    now = now or timezone.now()
    if kind not in IssueKind.values:
        raise BusinessRuleViolation("Choose what's wrong.", field="kind")
    if source == IssueSource.RIDER and kind not in RIDER_KINDS:
        raise BusinessRuleViolation("Choose what's wrong.", field="kind")
    if severity is None or kind in GROUNDING_KINDS:
        severity = (
            IssueSeverity.CRITICAL
            if kind in GROUNDING_KINDS
            else IssueSeverity.MINOR
            if source == IssueSource.RIDER
            else IssueSeverity.MAJOR
        )
    if severity not in IssueSeverity.values:
        raise BusinessRuleViolation("Choose how serious it is.", field="severity")
    if source == IssueSource.RIDER:
        severity = IssueSeverity.MINOR if severity == IssueSeverity.CRITICAL else severity
        if VehicleIssue.objects.filter(
            vehicle=vehicle, trip=trip, source=IssueSource.RIDER
        ).exists():
            raise BusinessRuleViolation("You've already reported this car for this ride.")
    issue = VehicleIssue.objects.create(
        vehicle=vehicle,
        source=source,
        kind=kind,
        severity=severity,
        description=description[:300],
        trip=trip,
        reported_by=user,
        opened_at=now,
    )
    if severity == IssueSeverity.CRITICAL:
        set_condition(
            vehicle,
            VehicleCondition.OFF_ROAD,
            note=f"{issue.get_kind_display()}: {description}"[:200].rstrip(": "),
            now=now,
        )
        if source == IssueSource.DRIVER and kind == IssueKind.BREAKDOWN:
            _rescue_rider(vehicle, now=now)
    elif source == IssueSource.RIDER:
        for person in _people(vehicle):
            notify(
                person,
                f"A rider reported {issue.get_kind_display().lower()} "
                f"in {vehicle.registration_number}",
                description or "Please take a look before your next ride.",
                level=Level.WARNING,
            )
    return issue


def _rescue_rider(vehicle: Vehicle, *, now) -> None:
    """A breakdown with a rider on board or on the way: they pay nothing and get a new car."""
    from apps.rides import services as rides
    from apps.rides.models import TripStatus as Status
    from apps.support import services as support

    trip = (
        Trip.objects.filter(
            driver=vehicle.driver,
            status__in=[Status.DRIVER_ASSIGNED, Status.DRIVER_ARRIVED, Status.IN_PROGRESS],
        )
        .select_related("rider__user")
        .first()
    )
    if trip is None:
        return
    if trip.status != Status.IN_PROGRESS:
        rides.cancel_trip(trip, user=vehicle.driver.user, reason="Vehicle breakdown", now=now)
        return
    # On board: ops ends the ride at no charge and support follows up.
    from apps.accounts.models import User

    system = User.objects.filter(is_superuser=True).order_by("pk").first()
    rides.cancel_trip(
        trip,
        user=system,
        reason="Your car broke down. You won't be charged; book a replacement from where you are.",
        now=now,
    )
    support.open_ticket(
        user=trip.rider.user,
        category="SAFETY",
        subject=f"Breakdown during {trip.trip_number}",
        description=f"{vehicle.registration_number} broke down mid-ride. Check the rider got home.",
        trip=trip,
        priority="HIGH",
        now=now,
    )


def submit_inspection(vehicle: Vehicle, *, driver, items: dict, now=None) -> VehicleInspection:
    now = now or timezone.now()
    unknown = set(items) - set(CHECKLIST)
    if unknown or set(CHECKLIST) - set(items):
        raise BusinessRuleViolation("Answer every item on the checklist.", field="items")
    answers = {k: bool(items[k]) for k in CHECKLIST}
    failed = [k for k, ok in answers.items() if not ok]
    inspection = VehicleInspection.objects.create(
        vehicle=vehicle,
        driver=driver,
        inspected_on=timezone.localdate(now),
        items=answers,
        passed=not any(k in CRITICAL_ITEMS for k in failed),
        created_at=now,
    )
    for item in failed:
        kind = CRITICAL_ITEMS.get(
            item, IssueKind.CLEANLINESS if item == "clean" else IssueKind.OTHER
        )
        if (
            vehicle.issues.filter(kind=kind, source=IssueSource.INSPECTION)
            .exclude(status=IssueStatus.RESOLVED)
            .exists()
        ):
            continue  # already reported and still open
        report_issue(
            vehicle,
            user=driver.user,
            source=IssueSource.INSPECTION,
            kind=kind,
            severity=IssueSeverity.CRITICAL if item in CRITICAL_ITEMS else IssueSeverity.MINOR,
            description=f"Daily check failed: {CHECKLIST[item]}",
            now=now,
        )
    return inspection


def costs(vehicle: Vehicle, *, days: int = 365) -> dict:
    """Upkeep spend and cost per km over the period."""
    from decimal import Decimal

    since = timezone.localdate() - timedelta(days=days)
    records = vehicle.service_records.filter(serviced_on__gte=since)
    spend = sum((r.parts_cost + r.labour_cost for r in records), Decimal(0))
    km = Trip.objects.filter(
        vehicle=vehicle, status=TripStatus.COMPLETED, completed_at__date__gte=since
    ).aggregate(km=Sum("actual_distance_km"))["km"]
    return {
        "days": days,
        "visits": records.count(),
        "spend": str(spend),
        "km": int(km or 0),
        "cost_per_km": str((spend / Decimal(km)).quantize(Decimal("0.01"))) if km else None,
    }


def history(vehicle: Vehicle, *, limit: int = 20) -> list[dict]:
    return [
        {
            "id": r.pk,
            "kind": r.kind,
            "kind_label": r.get_kind_display(),
            "serviced_on": r.serviced_on.isoformat(),
            "odometer_km": r.odometer_km,
            "workshop": r.workshop,
            "notes": r.notes,
            "parts": r.parts,
            "parts_cost": str(r.parts_cost),
            "labour_cost": str(r.labour_cost),
            "total_cost": str(r.parts_cost + r.labour_cost),
            "invoice_number": r.invoice_number,
            "fixed": [i.get_kind_display() for i in r.fixed.all()],
        }
        for r in vehicle.service_records.prefetch_related("fixed")[:limit]
    ]


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
    vehicles = with_health_data(
        Vehicle.objects.filter(is_active=True).select_related(
            "ride_type", "driver__user", "owner__user"
        )
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


def _spend(city_id: int | None, *, days: int):
    from decimal import Decimal

    totals = ServiceRecord.objects.filter(
        serviced_on__gte=timezone.localdate() - timedelta(days=days),
        **({"vehicle__driver__city_id": city_id} if city_id else {}),
    ).aggregate(parts=Sum("parts_cost"), labour=Sum("labour_cost"))
    return (totals["parts"] or Decimal(0)) + (totals["labour"] or Decimal(0))


def fleet_health(*, city_id: int | None = None) -> dict:
    """Ops: vehicles needing attention, by status."""
    distances = dict(
        Trip.objects.filter(status=TripStatus.COMPLETED, vehicle__isnull=False)
        .values_list("vehicle_id")
        .annotate(km=Sum("actual_distance_km"))
        .values_list("vehicle_id", "km")
    )
    vehicles = with_health_data(
        Vehicle.objects.filter(is_active=True).select_related("ride_type", "driver__user")
    )
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
        "by_state": {
            state: sum(r["state"] == state for r in rows)
            for state in ("OK", "DUE", "OVERDUE", "IN_WORKSHOP", "OFF_ROAD")
        },
        "open_issues": sum(len(r["open_issues"]) for r in rows),
        "checked_today": sum(r["checked_today"] for r in rows),
        "spend_30d": str(_spend(city_id, days=30)),
        "attention": attention[:200],
    }
