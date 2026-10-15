from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.db.models import Q

from apps.audit.mixins import AuditedModel
from apps.core.models import LatitudeField, LongitudeField, TimeStampedModel
from apps.core.validators import format_registration, normalize_registration, registration_validator


class OnboardingStatus(models.TextChoices):
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS", "Awaiting documents"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    SUSPENDED = "SUSPENDED", "Suspended"


class Availability(models.TextChoices):
    OFFLINE = "OFFLINE", "Offline"
    ONLINE = "ONLINE", "Online"
    ON_TRIP = "ON_TRIP", "On a trip"


class Gender(models.TextChoices):
    FEMALE = "FEMALE", "Woman"
    MALE = "MALE", "Man"
    UNDISCLOSED = "UNDISCLOSED", "Prefer not to say"


class DriverProfile(AuditedModel, TimeStampedModel):
    # Location fields change every few seconds; auditing them would flood the trail.
    audit_exclude = (
        "created_at",
        "updated_at",
        "current_lat",
        "current_lng",
        "heading",
        "location_updated_at",
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="driver_profile"
    )
    city = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="drivers")
    license_number = models.CharField(max_length=20)
    license_expiry = models.DateField()
    onboarding_status = models.CharField(
        max_length=20, choices=OnboardingStatus.choices, default=OnboardingStatus.PENDING_DOCUMENTS
    )
    availability = models.CharField(
        max_length=8, choices=Availability.choices, default=Availability.OFFLINE
    )
    current_lat = LatitudeField(null=True, blank=True)
    current_lng = LongitudeField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)

    rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("5.00"))
    rating_count = models.PositiveIntegerField(default=0)
    acceptance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(100))
    completed_trips = models.PositiveIntegerField(default=0)
    cancelled_trips = models.PositiveIntegerField(default=0)
    safety_score = models.PositiveSmallIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.CharField(max_length=255, blank=True)
    # Used only to honour riders' "prefer a woman driver" choice.
    gender = models.CharField(max_length=11, choices=Gender.choices, default=Gender.UNDISCLOSED)
    # "Going home": only trips heading towards home, for an hour, twice a day.
    home_lat = models.FloatField(null=True, blank=True)
    home_lng = models.FloatField(null=True, blank=True)
    home_address = models.CharField(max_length=255, blank=True)
    going_home_until = models.DateTimeField(null=True, blank=True)
    going_home_day = models.DateField(null=True, blank=True)
    going_home_uses = models.PositiveSmallIntegerField(default=0)
    # Bike drivers carry parcels unless they opt out.
    accepts_parcels = models.BooleanField(default=True)
    # The fleet executive who onboards and looks after this driver partner.
    fleet_executive = models.ForeignKey(
        "accounts.StaffProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="drivers",
    )
    # Car drivers take intercity trips (hours away from home) only if they opt in.
    accepts_intercity = models.BooleanField(default=True)
    # Completed disability-awareness and boarding-assistance training.
    assist_trained = models.BooleanField(default=False)
    # Driver Wellbeing (see drivers.wellbeing): enforced rest after long driving stretches.
    break_until = models.DateTimeField(null=True, blank=True)
    break_warned_at = models.DateTimeField(null=True, blank=True)
    rest_bonus_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Dispatch only ever searches online drivers, so the index skips everyone else.
            models.Index(
                fields=["current_lat", "current_lng"],
                condition=Q(availability="ONLINE"),
                name="driver_online_location_idx",
            ),
            models.Index(fields=["city", "availability"], name="driver_city_availability_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5), name="driver_rating_range"
            ),
            models.CheckConstraint(
                condition=Q(availability="OFFLINE") | Q(onboarding_status="APPROVED"),
                name="driver_online_only_when_approved",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def name(self) -> str:
        return self.user.get_full_name() or self.user.email

    @property
    def active_vehicle(self):
        return next((v for v in self.vehicles.all() if v.is_active), None)

    @property
    def has_location(self) -> bool:
        return self.current_lat is not None and self.current_lng is not None


class FuelType(models.TextChoices):
    PETROL = "PETROL", "Petrol"
    DIESEL = "DIESEL", "Diesel"
    CNG = "CNG", "CNG"
    EV = "EV", "Electric"


class Vehicle(AuditedModel, TimeStampedModel):
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="vehicles")
    ride_type = models.ForeignKey(
        "pricing.RideType", on_delete=models.PROTECT, related_name="vehicles"
    )
    make = models.CharField(max_length=40)
    model = models.CharField(max_length=60)
    registration_number = models.CharField(
        max_length=12, unique=True, validators=[registration_validator]
    )
    year = models.PositiveSmallIntegerField()
    color = models.CharField(max_length=30)
    seats = models.PositiveSmallIntegerField(default=4)
    fuel_type = models.CharField(max_length=6, choices=FuelType.choices, default=FuelType.PETROL)
    is_active = models.BooleanField(default=True)
    # Upkeep: the odometer when it joined (trips add to it) and at the last service.
    odometer_base_km = models.PositiveIntegerField(default=0)
    last_service_km = models.PositiveIntegerField(default=0)
    insurance_expires_on = models.DateField(null=True, blank=True)
    permit_expires_on = models.DateField(null=True, blank=True)
    fitness_expires_on = models.DateField(null=True, blank=True)
    # The fleet owner who owns the car (blank: the driver owns it).
    owner = models.ForeignKey(
        "fleet.FleetOwner",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vehicles",
    )
    # EVs: battery level reported by the driver app (or the simulator).
    battery_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_updated_at = models.DateTimeField(null=True, blank=True)
    # Wheelchair-accessible vehicle (ramp or lift, secured wheelchair space).
    wheelchair_accessible = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_active", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver"], condition=Q(is_active=True), name="one_active_vehicle_per_driver"
            ),
            models.CheckConstraint(
                condition=Q(year__gte=2005) & Q(year__lte=2100), name="vehicle_year_sane"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.make} {self.model} · {self.registration_display}"

    def save(self, *args, **kwargs):
        self.registration_number = normalize_registration(self.registration_number)
        super().save(*args, **kwargs)

    @property
    def registration_display(self) -> str:
        return format_registration(self.registration_number)


class DocumentType(models.TextChoices):
    DRIVING_LICENSE = "DRIVING_LICENSE", "Driving licence"
    VEHICLE_RC = "VEHICLE_RC", "Vehicle registration (RC)"
    VEHICLE_INSURANCE = "VEHICLE_INSURANCE", "Vehicle insurance"
    POLICE_VERIFICATION = "POLICE_VERIFICATION", "Police verification"
    PAN = "PAN", "PAN card"


REQUIRED_DOCUMENTS = (
    DocumentType.DRIVING_LICENSE,
    DocumentType.VEHICLE_RC,
    DocumentType.VEHICLE_INSURANCE,
    DocumentType.POLICE_VERIFICATION,
)


class DocumentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    EXPIRED = "EXPIRED", "Expired"
    SUPERSEDED = "SUPERSEDED", "Superseded"


CURRENT_DOCUMENT_STATUSES = (DocumentStatus.PENDING, DocumentStatus.APPROVED)


class DriverDocument(TimeStampedModel):
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices)
    # Privacy by design: only the last four characters of the document number are stored.
    number_last4 = models.CharField(max_length=4, blank=True)
    file = models.FileField(upload_to="driver-documents/%Y/%m/", blank=True)
    expires_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["doc_type", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver", "doc_type"],
                condition=Q(status__in=["PENDING", "APPROVED"]),
                name="one_current_document_per_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} ({self.get_status_display()})"


class DriverSession(models.Model):
    """A stretch of time a driver spent online; used for utilisation and hours-online metrics."""

    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="sessions")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver"],
                condition=Q(ended_at__isnull=True),
                name="one_open_session_per_driver",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.driver_id} {self.started_at:%Y-%m-%d %H:%M}"


class LocationPing(models.Model):
    """Raw GPS trail. High-volume and append-only, so it gets a BRIN index and a retention job."""

    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="pings")
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="pings"
    )
    lat = LatitudeField()
    lng = LongitudeField()
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [
            BrinIndex(fields=["recorded_at"], name="ping_recorded_brin"),
            models.Index(fields=["trip", "recorded_at"], name="ping_trip_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.driver_id} @ {self.lat:.5f},{self.lng:.5f}"


class DriverGoalReward(models.Model):
    """A daily goal reached ("5 trips today: ₹75"), paid once into the driver's wallet."""

    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="goal_rewards")
    day = models.DateField()
    trips_target = models.PositiveSmallIntegerField()
    bonus = models.DecimalField(max_digits=8, decimal_places=2)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-day", "trips_target"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver", "day", "trips_target"], name="goal_reward_once_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.driver_id} {self.day} {self.trips_target} trips"


class DriverDayPass(models.Model):
    """Zero-commission day pass (like Namma Yatri / Rapido): a flat fee, and the driver keeps
    the whole fare on every trip that day (see drivers.day_pass)."""

    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name="day_passes")
    day = models.DateField()
    price = models.DecimalField(max_digits=6, decimal_places=2)
    payment_method = models.CharField(max_length=6)
    reference = models.CharField(max_length=24, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-day"]
        constraints = [
            models.UniqueConstraint(fields=["driver", "day"], name="one_day_pass_per_day"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.driver_id} {self.day}"
