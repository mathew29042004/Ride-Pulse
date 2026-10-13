from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, FloatField, Value
from django.db.models.functions import ASin, Cos, Power, Radians, Sin, Sqrt
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditAction
from apps.audit.services import log_event, log_transition
from apps.core.conf import location_ping_retention_days, location_stale_seconds, max_driver_dues
from apps.core.dates import today
from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.geo.distance import EARTH_RADIUS_KM, bounding_box
from apps.notifications.models import Level
from apps.notifications.services import notify

from . import safety
from .models import (
    CURRENT_DOCUMENT_STATUSES,
    REQUIRED_DOCUMENTS,
    Availability,
    DocumentStatus,
    DocumentType,
    DriverDocument,
    DriverProfile,
    DriverSession,
    LocationPing,
    OnboardingStatus,
    Vehicle,
)

EXPIRY_WARNING_DAYS = 15
STALE_OFFLINE_MINUTES = 10


# --- Onboarding --------------------------------------------------------------------------


@transaction.atomic
def register_driver(
    *,
    email: str,
    password: str | None,
    first_name: str,
    last_name: str = "",
    phone: str = "",
    city,
    license_number: str,
    license_expiry: date,
) -> DriverProfile:
    from apps.payments.services import ensure_wallet

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        raise BusinessRuleViolation("An account with this email already exists.", field="email")
    phone = _clean_phone(phone)
    if phone and User.objects.filter(phone=phone).exists():
        raise BusinessRuleViolation(
            "An account with this phone number already exists.", field="phone"
        )
    user = User.objects.create_user(
        email=email,
        password=password,
        role=Role.DRIVER,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    driver = DriverProfile.objects.create(
        user=user, city=city, license_number=license_number.upper(), license_expiry=license_expiry
    )
    ensure_wallet(user)
    return driver


@transaction.atomic
def register_vehicle(driver: DriverProfile, **fields) -> Vehicle:
    """Adds a vehicle and makes it the driver's only active one."""
    if driver.availability != Availability.OFFLINE:
        raise BusinessRuleViolation("Go offline before changing vehicles.")
    driver.vehicles.filter(is_active=True).update(is_active=False)
    vehicle = Vehicle.objects.create(driver=driver, is_active=True, **fields)
    _refresh_onboarding(driver)
    return vehicle


@transaction.atomic
def submit_document(
    driver: DriverProfile,
    *,
    doc_type: str,
    number_last4: str = "",
    expires_on: date | None = None,
    file=None,
) -> DriverDocument:
    """A new upload supersedes the current document of the same type."""
    DriverDocument.objects.filter(
        driver=driver, doc_type=doc_type, status__in=CURRENT_DOCUMENT_STATUSES
    ).update(status=DocumentStatus.SUPERSEDED, updated_at=timezone.now())
    document = DriverDocument.objects.create(
        driver=driver,
        doc_type=doc_type,
        number_last4=number_last4[-4:].upper(),
        expires_on=expires_on,
        **({"file": file} if file else {}),
    )
    _refresh_onboarding(driver)
    return document


@transaction.atomic
def review_document(
    document: DriverDocument, *, approve: bool, reviewer, reason: str = ""
) -> DriverDocument:
    if document.status != DocumentStatus.PENDING:
        raise InvalidStateTransition("Only pending documents can be reviewed.")
    if not approve and not reason.strip():
        raise BusinessRuleViolation("Give a reason when rejecting a document.", field="reason")
    if approve and document.expires_on and document.expires_on < today():
        raise BusinessRuleViolation("This document has already expired.", field="expires_on")
    document.status = DocumentStatus.APPROVED if approve else DocumentStatus.REJECTED
    document.reviewed_by = reviewer
    document.reviewed_at = timezone.now()
    document.rejection_reason = "" if approve else reason
    document.save()
    driver = document.driver
    if not approve:
        notify(
            driver.user,
            f"{document.get_doc_type_display()} was rejected",
            reason,
            level=Level.WARNING,
            link="/drive/documents/",
            email=True,
        )
    _refresh_onboarding(driver, actor=reviewer)
    return document


def missing_documents(driver: DriverProfile) -> list[str]:
    approved = set(
        driver.documents.filter(status=DocumentStatus.APPROVED).values_list("doc_type", flat=True)
    )
    return [d for d in REQUIRED_DOCUMENTS if d not in approved]


def _refresh_onboarding(driver: DriverProfile, *, actor=None) -> None:
    """Moves a driver through onboarding as documents arrive and are reviewed."""
    if driver.onboarding_status in (OnboardingStatus.SUSPENDED, OnboardingStatus.REJECTED):
        return
    current = {
        d.doc_type: d.status for d in driver.documents.filter(status__in=CURRENT_DOCUMENT_STATUSES)
    }
    has_vehicle = driver.vehicles.filter(is_active=True).exists()
    all_submitted = all(doc in current for doc in REQUIRED_DOCUMENTS)
    all_approved = all(current.get(doc) == DocumentStatus.APPROVED for doc in REQUIRED_DOCUMENTS)

    if all_approved and has_vehicle:
        target = OnboardingStatus.APPROVED
    elif all_submitted and has_vehicle:
        target = OnboardingStatus.UNDER_REVIEW
    else:
        target = OnboardingStatus.PENDING_DOCUMENTS
    if target == driver.onboarding_status:
        return
    if (
        driver.onboarding_status == OnboardingStatus.APPROVED
        and driver.availability != Availability.OFFLINE
    ):
        return  # a re-upload while driving is reviewed without knocking the driver offline
    previous = driver.onboarding_status
    driver.onboarding_status = target
    if target == OnboardingStatus.APPROVED:
        driver.approved_at = timezone.now()
    driver.save(update_fields=["onboarding_status", "approved_at", "updated_at"])
    log_transition(driver, previous, target, actor=actor)
    if target == OnboardingStatus.APPROVED:
        notify(
            driver.user,
            "You're approved to drive with Ride Pulse",
            "Go online from the driver app to start receiving trips.",
            level=Level.SUCCESS,
            link="/drive/",
            email=True,
        )


@transaction.atomic
def suspend_driver(driver: DriverProfile, *, reason: str, actor=None) -> DriverProfile:
    if not reason.strip():
        raise BusinessRuleViolation("A reason is required to suspend a driver.", field="reason")
    if driver.availability == Availability.ON_TRIP:
        raise BusinessRuleViolation("The driver is on a trip; suspend after it ends.")
    _close_session(driver, timezone.now())
    previous = driver.onboarding_status
    driver.onboarding_status = OnboardingStatus.SUSPENDED
    driver.availability = Availability.OFFLINE
    driver.suspended_reason = reason
    driver.save(
        update_fields=["onboarding_status", "availability", "suspended_reason", "updated_at"]
    )
    log_transition(driver, previous, OnboardingStatus.SUSPENDED, actor=actor, note=reason)
    notify(driver.user, "Your account is suspended", reason, level=Level.DANGER, email=True)
    return driver


@transaction.atomic
def reinstate_driver(driver: DriverProfile, *, actor=None) -> DriverProfile:
    if driver.onboarding_status != OnboardingStatus.SUSPENDED:
        raise InvalidStateTransition("Only suspended drivers can be reinstated.")
    driver.onboarding_status = OnboardingStatus.UNDER_REVIEW
    driver.suspended_reason = ""
    driver.save(update_fields=["onboarding_status", "suspended_reason", "updated_at"])
    _refresh_onboarding(driver, actor=actor)
    log_event(AuditAction.ACTION, driver, message="Reinstated", actor=actor)
    return driver


# --- Availability ------------------------------------------------------------------------


def compliance_problems(driver: DriverProfile, *, on: date | None = None) -> list[str]:
    """Everything that stops a driver from going online right now."""
    from apps.payments.services import wallet_balance

    on = on or today()
    problems = []
    if driver.onboarding_status != OnboardingStatus.APPROVED:
        problems.append(f"Onboarding status is {driver.get_onboarding_status_display().lower()}.")
    if not driver.vehicles.filter(is_active=True).exists():
        problems.append("No active vehicle registered.")
    if driver.license_expiry < on:
        problems.append("Driving licence has expired.")
    approved = {
        d.doc_type: d
        for d in driver.documents.filter(
            status=DocumentStatus.APPROVED, doc_type__in=REQUIRED_DOCUMENTS
        )
    }
    for doc_type in REQUIRED_DOCUMENTS:
        document = approved.get(doc_type)
        label = DocumentType(doc_type).label
        if document is None:
            problems.append(f"{label} is missing, pending review or expired.")
        elif document.expires_on and document.expires_on < on:
            problems.append(f"{label} has expired.")
    balance = wallet_balance(driver.user)
    if balance < -max_driver_dues():
        problems.append(
            f"Outstanding dues of ₹{-balance:,.2f} exceed the ₹{max_driver_dues():,.0f} limit."
        )
    return problems


def _close_session(driver: DriverProfile, now: datetime) -> None:
    DriverSession.objects.filter(driver=driver, ended_at__isnull=True).update(ended_at=now)


@transaction.atomic
def go_online(
    driver: DriverProfile, *, lat: float, lng: float, now: datetime | None = None
) -> DriverProfile:
    now = now or timezone.now()
    driver = DriverProfile.objects.select_for_update().get(pk=driver.pk)
    if driver.availability == Availability.ON_TRIP:
        raise InvalidStateTransition("You're on a trip.")
    problems = compliance_problems(driver, on=timezone.localdate(now))
    if problems:
        raise BusinessRuleViolation(" ".join(problems))
    if driver.availability == Availability.OFFLINE:
        DriverSession.objects.create(driver=driver, started_at=now)
    driver.availability = Availability.ONLINE
    driver.save(update_fields=["availability", "updated_at"])
    update_location(driver, lat=lat, lng=lng, now=now)
    return driver


@transaction.atomic
def go_offline(driver: DriverProfile, *, now: datetime | None = None) -> DriverProfile:
    from apps.rides.dispatch import withdraw_driver_offers

    now = now or timezone.now()
    driver = DriverProfile.objects.select_for_update().get(pk=driver.pk)
    if driver.availability == Availability.ON_TRIP:
        raise InvalidStateTransition("Finish the current trip before going offline.")
    _close_session(driver, now)
    driver.availability = Availability.OFFLINE
    driver.save(update_fields=["availability", "updated_at"])
    withdraw_driver_offers(driver, now=now)
    return driver


def update_location(
    driver: DriverProfile,
    *,
    lat: float,
    lng: float,
    speed_kmh: float | None = None,
    heading: float | None = None,
    now: datetime | None = None,
    record: bool = True,
) -> None:
    """Hot path: a single UPDATE (no model save, no audit) plus an append-only ping."""
    from apps.realtime import broadcast
    from apps.rides.models import ACTIVE_DRIVER_STATUSES, Trip

    now = now or timezone.now()
    DriverProfile.objects.filter(pk=driver.pk).update(
        current_lat=lat, current_lng=lng, heading=heading, location_updated_at=now
    )
    driver.current_lat, driver.current_lng = lat, lng
    driver.heading, driver.location_updated_at = heading, now
    trip_id = (
        Trip.objects.filter(driver=driver, status__in=ACTIVE_DRIVER_STATUSES)
        .values_list("pk", flat=True)
        .first()
    )
    if record:
        LocationPing.objects.create(
            driver=driver,
            trip_id=trip_id,
            lat=lat,
            lng=lng,
            speed_kmh=speed_kmh,
            heading=heading,
            recorded_at=now,
        )
    payload = {"driver_id": driver.pk, "lat": lat, "lng": lng, "heading": heading}
    if trip_id:
        broadcast.trip_event(trip_id, "driver_location", payload)
    broadcast.ops_event("driver_location", payload)


def haversine_expression(lat: float, lng: float):
    """Great-circle distance in km from (lat, lng) to each row, evaluated inside PostgreSQL."""
    d_lat = Radians(F("current_lat") - Value(lat))
    d_lng = Radians(F("current_lng") - Value(lng))
    a = Power(Sin(d_lat / 2), 2) + Cos(Radians(Value(lat))) * Cos(
        Radians(F("current_lat"))
    ) * Power(Sin(d_lng / 2), 2)
    return Value(2 * EARTH_RADIUS_KM, output_field=FloatField()) * ASin(Sqrt(a))


def nearby_available_drivers(
    *,
    lat: float,
    lng: float,
    radius_km: float,
    ride_type=None,
    now: datetime | None = None,
    exclude_ids=(),
    limit: int = 10,
):
    """Online, approved, recently-seen drivers within ``radius_km``, nearest first.

    The bounding-box filter is index-friendly (partial index on online drivers); the exact
    haversine distance is then computed and filtered in SQL.
    """
    now = now or timezone.now()
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    queryset = (
        DriverProfile.objects.filter(
            availability=Availability.ONLINE,
            onboarding_status=OnboardingStatus.APPROVED,
            current_lat__range=(min_lat, max_lat),
            current_lng__range=(min_lng, max_lng),
            location_updated_at__gte=now - timedelta(seconds=location_stale_seconds()),
        )
        .exclude(pk__in=list(exclude_ids))
        .annotate(distance_km=haversine_expression(lat, lng))
        .filter(distance_km__lte=radius_km)
        .select_related("user")
        .order_by("distance_km")
    )
    if ride_type is not None:
        queryset = queryset.filter(vehicles__is_active=True, vehicles__ride_type=ride_type)
    return list(queryset[:limit])


# --- Scheduled jobs ----------------------------------------------------------------------


def mark_stale_drivers_offline(*, now: datetime | None = None) -> int:
    """Drivers whose app stopped reporting (dead battery, no signal) stop receiving offers."""
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=STALE_OFFLINE_MINUTES)
    stale = list(
        DriverProfile.objects.filter(
            availability=Availability.ONLINE, location_updated_at__lt=cutoff
        )
    )
    for driver in stale:
        go_offline(driver, now=now)
    return len(stale)


def check_document_expiry(*, on: date | None = None) -> dict:
    on = on or today()
    expired = DriverDocument.objects.filter(status=DocumentStatus.APPROVED, expires_on__lt=on)
    expired_drivers = set(expired.values_list("driver_id", flat=True))
    expired_count = expired.update(status=DocumentStatus.EXPIRED, updated_at=timezone.now())
    for driver in DriverProfile.objects.filter(pk__in=expired_drivers).select_related("user"):
        _refresh_onboarding(driver)
        notify(
            driver.user,
            "A required document has expired",
            "Upload a renewed copy to keep driving.",
            level=Level.DANGER,
            link="/drive/documents/",
            email=True,
        )
    warn_on = on + timedelta(days=EXPIRY_WARNING_DAYS)
    expiring = DriverDocument.objects.filter(
        status=DocumentStatus.APPROVED, expires_on=warn_on
    ).select_related("driver__user")
    for document in expiring:
        notify(
            document.driver.user,
            f"{document.get_doc_type_display()} expires in {EXPIRY_WARNING_DAYS} days",
            "Upload the renewed document before it expires.",
            level=Level.WARNING,
            link="/drive/documents/",
        )
    return {"expired": expired_count, "warned": len(expiring)}


def purge_location_pings(*, now: datetime | None = None) -> int:
    cutoff = (now or timezone.now()) - timedelta(days=location_ping_retention_days())
    deleted, _ = LocationPing.objects.filter(recorded_at__lt=cutoff).delete()
    return deleted


def recompute_safety_score(driver: DriverProfile, *, last_trips: int = 50) -> int | None:
    from apps.rides.models import Trip, TripStatus

    trips = Trip.objects.filter(driver=driver, status=TripStatus.COMPLETED).order_by(
        "-completed_at"
    )[:last_trips]
    metrics = [t.telemetry() for t in trips if t.actual_distance_km]
    result = safety.aggregate(metrics)
    score = result[0] if result else None
    DriverProfile.objects.filter(pk=driver.pk).update(safety_score=score)
    driver.safety_score = score
    return score


def _clean_phone(phone: str) -> str:
    """Store numbers in one format (10 digits) so phone login finds the account."""
    from apps.core.validators import normalize_indian_mobile

    if not phone:
        return ""
    try:
        return normalize_indian_mobile(phone)
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="phone") from exc
