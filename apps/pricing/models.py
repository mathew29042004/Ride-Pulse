from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel

from .fare import FareCard, PromoTerms


class Service(models.TextChoices):
    RIDE = "RIDE", "Ride"
    PARCEL = "PARCEL", "Parcel delivery"
    RENTAL = "RENTAL", "Hourly rental"
    INTERCITY = "INTERCITY", "Intercity"


class RideType(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=40)
    description = models.CharField(max_length=120)
    seats = models.PositiveSmallIntegerField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Local hours this ride type runs (e.g. bike taxis 5 am – 11 pm). Blank = round the clock.
    service_start_hour = models.PositiveSmallIntegerField(null=True, blank=True)
    service_end_hour = models.PositiveSmallIntegerField(null=True, blank=True)
    # What it's booked for (rides or parcels), and which vehicles serve it: a Parcel is carried
    # by Bike drivers, so ``vehicle_type`` points at BIKE. Blank = vehicles of this type.
    service = models.CharField(max_length=10, choices=Service.choices, default=Service.RIDE)
    vehicle_type = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return self.name

    @property
    def served_by(self) -> "RideType":
        return self.vehicle_type or self

    def is_open(self, at) -> bool:
        from django.utils import timezone

        if self.service_start_hour is None or self.service_end_hour is None:
            return True
        hour = timezone.localtime(at).hour
        start, end = self.service_start_hour, self.service_end_hour
        return start <= hour < end if start < end else hour >= start or hour < end

    @property
    def service_hours_label(self) -> str:
        def fmt(hour: int) -> str:
            return f"{hour % 12 or 12} {'am' if hour < 12 else 'pm'}"

        if self.service_start_hour is None or self.service_end_hour is None:
            return ""
        return f"{fmt(self.service_start_hour)} – {fmt(self.service_end_hour)}"


class FareRule(TimeStampedModel):
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="fare_rules")
    ride_type = models.ForeignKey(RideType, on_delete=models.CASCADE, related_name="fare_rules")
    base_fare = models.DecimalField(max_digits=8, decimal_places=2)
    per_km = models.DecimalField(max_digits=6, decimal_places=2)
    per_minute = models.DecimalField(max_digits=6, decimal_places=2)
    minimum_fare = models.DecimalField(max_digits=8, decimal_places=2)
    booking_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    cancellation_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    free_wait_minutes = models.PositiveSmallIntegerField(default=3)
    wait_per_minute = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    airport_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["city__name", "ride_type__sort_order"]
        constraints = [
            models.UniqueConstraint(fields=["city", "ride_type"], name="fare_rule_city_ride_type"),
            models.CheckConstraint(
                condition=Q(minimum_fare__gte=F("base_fare")), name="fare_minimum_covers_base"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ride_type} in {self.city}"

    def card(self) -> FareCard:
        return FareCard(
            base_fare=self.base_fare,
            per_km=self.per_km,
            per_minute=self.per_minute,
            minimum_fare=self.minimum_fare,
            booking_fee=self.booking_fee,
            free_wait_minutes=Decimal(self.free_wait_minutes),
            wait_per_minute=self.wait_per_minute,
            airport_fee=self.airport_fee,
        )


class SurgeSnapshot(models.Model):
    zone = models.ForeignKey("geo.Zone", on_delete=models.CASCADE, related_name="surge_snapshots")
    multiplier = models.DecimalField(max_digits=3, decimal_places=1)
    demand = models.PositiveIntegerField()
    supply = models.PositiveIntegerField()
    computed_at = models.DateTimeField()

    class Meta:
        ordering = ["-computed_at"]
        indexes = [models.Index(fields=["zone", "-computed_at"], name="surge_zone_time_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(multiplier__gte=1), name="surge_at_least_one")
        ]

    def __str__(self) -> str:
        return f"{self.zone} {self.multiplier}× @ {self.computed_at:%H:%M}"


class SurgeOverride(models.Model):
    """Manual surge set by operations, e.g. for a concert or heavy rain."""

    zone = models.ForeignKey("geo.Zone", on_delete=models.CASCADE, related_name="surge_overrides")
    multiplier = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        validators=[MinValueValidator(Decimal(1)), MaxValueValidator(Decimal(5))],
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=160)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="override_window"),
            models.CheckConstraint(
                condition=Q(multiplier__gte=1) & Q(multiplier__lte=5),
                name="override_multiplier_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.zone}: {self.multiplier}× ({self.reason})"


class DiscountType(models.TextChoices):
    PERCENT = "PERCENT", "Percent off"
    FLAT = "FLAT", "Flat amount off"


class PromoCode(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=160)
    discount_type = models.CharField(max_length=7, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=8, decimal_places=2)
    max_discount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    min_fare = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    max_per_rider = models.PositiveSmallIntegerField(default=1)
    first_ride_only = models.BooleanField(default=False)
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.CASCADE, help_text="Empty = all cities"
    )
    ride_types = ArrayField(
        models.CharField(max_length=10),
        default=list,
        blank=True,
        help_text="Empty = all ride types",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-valid_until"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_until__gt=F("valid_from")), name="promo_window"
            ),
            models.CheckConstraint(
                condition=~Q(discount_type="PERCENT") | Q(value__lte=100),
                name="promo_percent_max_100",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def terms(self) -> PromoTerms:
        return PromoTerms(
            code=self.code,
            discount_type=self.discount_type,
            value=self.value,
            max_discount=self.max_discount,
            min_fare=self.min_fare,
        )


class PromoRedemption(models.Model):
    promo = models.ForeignKey(PromoCode, on_delete=models.PROTECT, related_name="redemptions")
    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="promo_redemptions"
    )
    trip = models.OneToOneField(
        "rides.Trip", on_delete=models.CASCADE, related_name="promo_redemption"
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.promo.code} on {self.trip_id}"


class RidePass(models.Model):
    """A rider's monthly Ride Pass: % off every ride and no booking fee until ``ends_at``.
    Buying again before it ends extends it (the new period starts when the old one ends)."""

    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="passes"
    )
    price = models.DecimalField(max_digits=8, decimal_places=2)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    payment_method = models.CharField(max_length=6)
    reference = models.CharField(max_length=24, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ends_at"]
        indexes = [models.Index(fields=["rider", "ends_at"], name="ride_pass_rider_end_idx")]

    def __str__(self) -> str:
        return f"{self.reference} ({self.starts_at:%d %b} – {self.ends_at:%d %b})"


class PriceAlertStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Watching"
    NOTIFIED = "NOTIFIED", "Prices dropped"
    EXPIRED = "EXPIRED", "Expired"
    CANCELLED = "CANCELLED", "Cancelled"


class PriceAlert(models.Model):
    """A rider's "tell me when prices drop": watches surge on a route, notifies when it eases."""

    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="price_alerts"
    )
    ride_type = models.ForeignKey(RideType, on_delete=models.CASCADE, related_name="+")
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="+")
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    pickup_address = models.CharField(max_length=255, blank=True)
    dropoff_lat = models.FloatField()
    dropoff_lng = models.FloatField()
    dropoff_address = models.CharField(max_length=255, blank=True)
    fare_when_set = models.DecimalField(max_digits=10, decimal_places=2)
    surge_when_set = models.DecimalField(max_digits=4, decimal_places=2)
    status = models.CharField(
        max_length=9, choices=PriceAlertStatus.choices, default=PriceAlertStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    notified_at = models.DateTimeField(null=True, blank=True)
    fare_when_notified = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["expires_at"],
                name="price_alert_active_idx",
                condition=models.Q(status="ACTIVE"),
            )
        ]

    def __str__(self) -> str:
        return f"{self.rider_id} {self.ride_type_id} ({self.status})"
