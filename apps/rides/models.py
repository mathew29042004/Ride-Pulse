from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.audit.mixins import AuditedModel
from apps.core.dates import minutes_between
from apps.core.models import LatitudeField, LongitudeField, TimeStampedModel
from apps.drivers.safety import TripMetrics
from apps.pricing.fare import FareBreakdown


class TripStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Finding a driver"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED", "Driver on the way"
    DRIVER_ARRIVED = "DRIVER_ARRIVED", "Driver has arrived"
    IN_PROGRESS = "IN_PROGRESS", "On trip"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    NO_DRIVER_FOUND = "NO_DRIVER_FOUND", "No driver found"


ACTIVE_STATUSES = [
    TripStatus.REQUESTED,
    TripStatus.DRIVER_ASSIGNED,
    TripStatus.DRIVER_ARRIVED,
    TripStatus.IN_PROGRESS,
]
ACTIVE_DRIVER_STATUSES = [
    TripStatus.DRIVER_ASSIGNED,
    TripStatus.DRIVER_ARRIVED,
    TripStatus.IN_PROGRESS,
]
TERMINAL_STATUSES = [TripStatus.COMPLETED, TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND]


class CancelledBy(models.TextChoices):
    RIDER = "RIDER", "Rider"
    DRIVER = "DRIVER", "Driver"
    OPS = "OPS", "Operations"
    SYSTEM = "SYSTEM", "System"


class TripPaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    DUES = "DUES", "Unpaid (rider dues)"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"


class RidePreference(models.TextChoices):
    QUIET = "QUIET", "Quiet ride"
    AC = "AC", "AC on"
    LUGGAGE = "LUGGAGE", "Extra luggage"
    WOMAN_DRIVER = "WOMAN_DRIVER", "Woman driver preferred"
    ELECTRIC = "ELECTRIC", "Electric vehicle preferred"
    # Accessibility: a wheelchair-accessible vehicle is a hard requirement; the others tell the
    # driver how to help (and earn extra free waiting time).
    WHEELCHAIR = "WHEELCHAIR", "Wheelchair-accessible vehicle"
    ASSIST = "ASSIST", "Help getting in and out"
    HEARING = "HEARING", "Deaf or hard of hearing: message, don't call"
    LOW_VISION = "LOW_VISION", "Blind or low vision: please find me"


# AC and luggage only make sense in a car.
CAR_ONLY_PREFERENCES = {RidePreference.AC, RidePreference.LUGGAGE, RidePreference.WHEELCHAIR}
ACCESSIBILITY_NEEDS = {
    RidePreference.WHEELCHAIR,
    RidePreference.ASSIST,
    RidePreference.HEARING,
    RidePreference.LOW_VISION,
}
# Riders who need more time to board get this much extra free waiting at the pickup.
ACCESSIBLE_EXTRA_WAIT_MINUTES = 5


class PricingMode(models.TextChoices):
    UPFRONT = "UPFRONT", "Upfront price honoured"
    METERED = "METERED", "Re-priced on actual route"


class TripFlag(models.TextChoices):
    ROUTE_DEVIATION = "ROUTE_DEVIATION", "Route much longer than estimated"
    LONG_PICKUP = "LONG_PICKUP", "Pickup took much longer than the ETA"
    SOS = "SOS", "SOS raised"
    LOW_RATING = "LOW_RATING", "Rated 2 stars or less"
    GPS_JUMP = "GPS_JUMP", "GPS jumped impossibly far (glitch or spoofing)"
    RIDE_CHECK = "RIDE_CHECK", "Ride Check escalated to the safety team"


class ParcelCategory(models.TextChoices):
    DOCUMENTS = "DOCUMENTS", "Documents"
    FOOD = "FOOD", "Food"
    ELECTRONICS = "ELECTRONICS", "Electronics"
    CLOTHES = "CLOTHES", "Clothes"
    KEYS = "KEYS", "Keys"
    OTHER = "OTHER", "Other"


class Trip(AuditedModel, TimeStampedModel):
    audit_exclude = (
        "created_at",
        "updated_at",
        "fare_estimate",
        "fare_breakdown",
        "route_polyline",
    )

    trip_number = models.CharField(max_length=24, unique=True)
    rider = models.ForeignKey("riders.RiderProfile", on_delete=models.PROTECT, related_name="trips")
    driver = models.ForeignKey(
        "drivers.DriverProfile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trips",
    )
    vehicle = models.ForeignKey(
        "drivers.Vehicle", null=True, blank=True, on_delete=models.PROTECT, related_name="trips"
    )
    ride_type = models.ForeignKey(
        "pricing.RideType", on_delete=models.PROTECT, related_name="trips"
    )
    city = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="trips")
    pickup_zone = models.ForeignKey(
        "geo.Zone", null=True, blank=True, on_delete=models.SET_NULL, related_name="pickups"
    )
    dropoff_zone = models.ForeignKey(
        "geo.Zone", null=True, blank=True, on_delete=models.SET_NULL, related_name="dropoffs"
    )
    pickup_lat = LatitudeField()
    pickup_lng = LongitudeField()
    pickup_address = models.CharField(max_length=255, blank=True)
    pickup_geohash = models.CharField(max_length=7)
    dropoff_lat = LatitudeField()
    dropoff_lng = LongitudeField()
    dropoff_address = models.CharField(max_length=255, blank=True)
    # One optional stop on the way.
    stop_lat = LatitudeField(null=True, blank=True)
    stop_lng = LongitudeField(null=True, blank=True)
    stop_address = models.CharField(max_length=255, blank=True)
    # Further stops after the first, in order: [{"lat", "lng", "address"}] (3 stops in all).
    extra_stops = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=16, choices=TripStatus.choices, default=TripStatus.REQUESTED
    )
    otp = models.CharField(max_length=4, help_text="Ride PIN the rider tells the driver at pickup")
    # Wrong ride-PIN entries; after MAX_PIN_ATTEMPTS the trip can't be started (anti-guessing).
    pin_attempts = models.PositiveSmallIntegerField(default=0)
    # Pickup verification: the rider's phone location (only while plausibly near the trip),
    # the rider's "yes, this is my car" tap, and the rider-left-the-car alert.
    rider_lat = LatitudeField(null=True, blank=True)
    rider_lng = LongitudeField(null=True, blank=True)
    rider_location_at = models.DateTimeField(null=True, blank=True)
    car_confirmed_at = models.DateTimeField(null=True, blank=True)
    separation_alerted_at = models.DateTimeField(null=True, blank=True)
    # Invoice: numbered when the fare is paid, then emailed to the rider (once, unless resent).
    invoice_number = models.CharField(max_length=24, blank=True)
    invoice_emailed_at = models.DateTimeField(null=True, blank=True)
    # Boost: extra the rider adds while searching (100% to the driver, widens dispatch), and a
    # tip promised at booking, collected with the fare.
    boost_amount = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal(0))
    boosted_at = models.DateTimeField(null=True, blank=True)
    dispatch_round = models.PositiveSmallIntegerField(default=0)
    tip_pledged = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal(0))
    preferences = ArrayField(
        models.CharField(max_length=12, choices=RidePreference.choices), default=list, blank=True
    )
    # Booked with an active Ride Pass: its discount applies to this ride's final fare too.
    ride_pass_applied = models.BooleanField(default=False)
    payment_method = models.CharField(max_length=6)
    promo = models.ForeignKey(
        "pricing.PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="trips"
    )

    # Upfront estimate shown to the rider at booking time.
    estimated_distance_km = models.DecimalField(max_digits=7, decimal_places=2)
    estimated_duration_min = models.DecimalField(max_digits=7, decimal_places=2)
    surge_multiplier = models.DecimalField(max_digits=3, decimal_places=1, default=Decimal(1))
    estimated_fare = models.DecimalField(max_digits=10, decimal_places=2)
    fare_estimate = models.JSONField(default=dict)
    route_polyline = models.TextField(blank=True, help_text="Encoded road route (Google)")
    # Secret for the public "follow my ride" page; set when the rider first shares the trip.
    share_token = models.CharField(max_length=32, null=True, blank=True, unique=True)
    # Ride, parcel delivery, hourly rental or intercity (see pricing.models.Service).
    service = models.CharField(max_length=10, default="RIDE")
    # Fare Lock that set this trip's price (see pricing.fare_locks).
    fare_lock = models.ForeignKey(
        "pricing.FareLock", null=True, blank=True, on_delete=models.SET_NULL, related_name="trips"
    )
    # Family or business profile that pays for this trip, and the business trip purpose.
    payment_profile = models.ForeignKey(
        "riders.PaymentProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trips",
    )
    trip_purpose = models.CharField(max_length=120, blank=True)
    cost_center = models.CharField(max_length=40, blank=True)
    # Shared rides: trips carried together by one driver share a pool id (the first trip's
    # number). Pooled trips are the only way a driver has more than one active trip.
    pool_id = models.CharField(max_length=20, blank=True, default="", db_index=True)
    # A teen's ride: top-rated drivers only, followed live by the parent.
    is_teen = models.BooleanField(default=False)
    # Zero-commission day pass: the commission the driver kept on this trip.
    commission_waived = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal(0))
    # Eco score: CO2 saved vs driving your own car, and the points it earned.
    co2_saved_g = models.PositiveIntegerField(default=0)
    # Hourly rentals and intercity trips (see rides.packages).
    package_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    package_km = models.PositiveSmallIntegerField(null=True, blank=True)
    round_trip = models.BooleanField(default=False)
    trip_days = models.PositiveSmallIntegerField(default=1)
    # Bid your fare (see rides.bids): the rider's offered total, and the agreed difference from
    # the usual fare (applied like a boost: all of it is the driver's).
    fare_offer = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    offer_adjustment = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal(0))
    # Sure Ride: "driver at pickup within N minutes or ₹30 back".
    sure_ride_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    sure_ride_deadline = models.DateTimeField(null=True, blank=True)
    sure_ride_refunded_at = models.DateTimeField(null=True, blank=True)
    # Night Safe mode (see rides.safety): decided when the trip starts.
    night_safe = models.BooleanField(default=False)
    contacts_notified_at = models.DateTimeField(null=True, blank=True)
    early_drop_confirmed = models.BooleanField(default=False)
    home_safe_at = models.DateTimeField(null=True, blank=True)
    route_source = models.CharField(max_length=10, default="estimate")

    requested_at = models.DateTimeField(default=timezone.now)
    dispatch_deadline = models.DateTimeField()
    assigned_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    pickup_eta_min = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dispatch_attempts = models.PositiveSmallIntegerField(default=0)

    cancelled_by = models.CharField(max_length=6, choices=CancelledBy.choices, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    cancellation_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal(0))

    actual_distance_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    actual_duration_min = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    waiting_minutes = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    pricing_mode = models.CharField(max_length=7, choices=PricingMode.choices, blank=True)
    fare_breakdown = models.JSONField(default=dict, blank=True)
    fare_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    driver_earning = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    platform_commission = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0))
    tip_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal(0))
    payment_status = models.CharField(
        max_length=14, choices=TripPaymentStatus.choices, default=TripPaymentStatus.PENDING
    )

    # Telemetry reported by the driver app at the end of the trip (feeds the safety score).
    harsh_brakes = models.PositiveSmallIntegerField(default=0)
    harsh_accelerations = models.PositiveSmallIntegerField(default=0)
    speeding_seconds = models.PositiveIntegerField(default=0)
    night_distance_km = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal(0))
    flags = ArrayField(
        models.CharField(max_length=20, choices=TripFlag.choices), default=list, blank=True
    )

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "-requested_at"], name="trip_status_idx"),
            models.Index(fields=["city", "-requested_at"], name="trip_city_time_idx"),
            models.Index(fields=["driver", "-requested_at"], name="trip_driver_idx"),
            models.Index(fields=["rider", "-requested_at"], name="trip_rider_idx"),
            # The dispatcher polls open requests constantly; this index holds only those rows.
            models.Index(
                fields=["dispatch_deadline"],
                condition=Q(status="REQUESTED"),
                name="trip_open_requests_idx",
            ),
        ]
        constraints = [
            # Database-enforced invariants that survive any race between app servers:
            models.UniqueConstraint(
                fields=["rider"],
                condition=Q(status__in=ACTIVE_STATUSES),
                name="one_active_trip_per_rider",
                violation_error_message="This rider already has an active trip.",
            ),
            models.UniqueConstraint(
                fields=["driver"],
                condition=Q(status__in=ACTIVE_DRIVER_STATUSES, pool_id=""),
                name="one_active_trip_per_driver",
                violation_error_message="This driver is already on a trip.",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=[*ACTIVE_DRIVER_STATUSES, TripStatus.COMPLETED])
                | Q(driver__isnull=False),
                name="trip_has_driver_once_assigned",
            ),
            models.CheckConstraint(
                condition=~Q(status=TripStatus.COMPLETED) | Q(fare_total__isnull=False),
                name="trip_completed_has_fare",
            ),
            models.CheckConstraint(condition=Q(tip_amount__gte=0), name="trip_tip_non_negative"),
        ]

    def __str__(self) -> str:
        return self.trip_number

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def stop(self) -> tuple[float, float] | None:
        return (self.stop_lat, self.stop_lng) if self.stop_lat is not None else None

    @property
    def waypoints(self) -> list[tuple[float, float]]:
        """Pickup, the stop (if any) and the drop, in order."""
        stop = [self.stop] if self.stop else []
        return [(self.pickup_lat, self.pickup_lng), *stop, (self.dropoff_lat, self.dropoff_lng)]

    @property
    def estimate(self) -> FareBreakdown:
        return FareBreakdown.from_dict(self.fare_estimate)

    @property
    def final_fare(self) -> FareBreakdown:
        return FareBreakdown.from_dict(self.fare_breakdown or self.fare_estimate)

    @property
    def wait_for_driver_minutes(self) -> float | None:
        return minutes_between(self.requested_at, self.assigned_at)

    @property
    def pickup_minutes(self) -> float | None:
        return minutes_between(self.assigned_at, self.arrived_at)

    def telemetry(self) -> TripMetrics:
        return TripMetrics(
            distance_km=float(self.actual_distance_km or 0),
            duration_minutes=float(self.actual_duration_min or 0),
            harsh_brakes=self.harsh_brakes,
            harsh_accelerations=self.harsh_accelerations,
            speeding_seconds=self.speeding_seconds,
            night_distance_km=float(self.night_distance_km),
        )


class TripEvent(models.Model):
    """The trip timeline: status changes plus dispatch and safety events."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=30)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    message = models.CharField(max_length=255, blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.trip_id} {self.kind}"


class OfferStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting for driver"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
    EXPIRED = "EXPIRED", "Timed out"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    COUNTERED = "COUNTERED", "Driver made a counter-offer"


class TripOffer(models.Model):
    """A trip offered to one driver, who has a few seconds to accept."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="offers")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="offers"
    )
    status = models.CharField(
        max_length=9, choices=OfferStatus.choices, default=OfferStatus.PENDING
    )
    offered_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    distance_km = models.FloatField()
    eta_minutes = models.FloatField()
    rank_score = models.FloatField()
    dispatch_mode = models.CharField(max_length=10, default="SEQUENTIAL")

    # Dispatch round: 0 for the original request, +1 after each boost.
    round = models.PositiveSmallIntegerField(default=0)
    # Bid your fare: the total this driver would do the trip for, instead of the rider's offer.
    counter_amount = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-offered_at"]
        indexes = [
            models.Index(
                fields=["expires_at"],
                condition=Q(status="PENDING"),
                name="offer_pending_expiry_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["trip"], condition=Q(status="PENDING"), name="one_pending_offer_per_trip"
            ),
            models.UniqueConstraint(
                fields=["driver"],
                condition=Q(status="PENDING"),
                name="one_pending_offer_per_driver",
            ),
            # Each driver is asked once per round; a boost starts a new round.
            models.UniqueConstraint(
                fields=["trip", "driver", "round"], name="offer_driver_once_per_round"
            ),
        ]

    def __str__(self) -> str:
        return f"Offer {self.trip_id} → {self.driver_id} ({self.status})"


class RatingDirection(models.TextChoices):
    RIDER_TO_DRIVER = "RIDER_TO_DRIVER", "Rider rated driver"
    DRIVER_TO_RIDER = "DRIVER_TO_RIDER", "Driver rated rider"


class TripRating(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="ratings")
    direction = models.CharField(max_length=15, choices=RatingDirection.choices)
    stars = models.PositiveSmallIntegerField()
    tags = ArrayField(models.CharField(max_length=30), default=list, blank=True)
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "direction"], name="one_rating_per_direction"),
            models.CheckConstraint(
                condition=Q(stars__gte=1) & Q(stars__lte=5), name="rating_stars_1_to_5"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trip_id} {self.direction} {self.stars}★"


class TripMessage(models.Model):
    """In-trip chat between the rider and the driver (kept for support and safety reviews)."""

    class Sender(models.TextChoices):
        RIDER = "RIDER", "Rider"
        DRIVER = "DRIVER", "Driver"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=6, choices=Sender.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.CharField(max_length=500)
    # Language Bridge: the message in the other person's language (rides.translate).
    language = models.CharField(max_length=2, blank=True)
    translations = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["trip", "created_at"])]

    def __str__(self) -> str:
        return f"{self.trip_id} {self.sender}: {self.body[:30]}"


class ScheduledRideStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    DISPATCHED = "DISPATCHED", "Driver requested"
    CANCELLED = "CANCELLED", "Cancelled"
    FAILED = "FAILED", "Couldn't book"


class ScheduledRide(TimeStampedModel):
    """A ride booked for later. Shortly before pickup time it becomes an ordinary trip request
    (see ``services.dispatch_scheduled_rides``), so dispatch, pricing and payment work as usual."""

    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="scheduled_rides"
    )
    ride_type = models.ForeignKey("pricing.RideType", on_delete=models.PROTECT, related_name="+")
    city = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="+")
    pickup_lat = LatitudeField()
    pickup_lng = LongitudeField()
    pickup_address = models.CharField(max_length=255, blank=True)
    dropoff_lat = LatitudeField()
    dropoff_lng = LongitudeField()
    dropoff_address = models.CharField(max_length=255, blank=True)
    # One optional stop on the way.
    stop_lat = LatitudeField(null=True, blank=True)
    stop_lng = LongitudeField(null=True, blank=True)
    stop_address = models.CharField(max_length=255, blank=True)
    # Further stops after the first, in order: [{"lat", "lng", "address"}] (3 stops in all).
    extra_stops = models.JSONField(default=list, blank=True)
    payment_method = models.CharField(max_length=10)
    promo_code = models.CharField(max_length=20, blank=True)
    scheduled_for = models.DateTimeField()
    quoted_fare = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=ScheduledRideStatus.choices, default=ScheduledRideStatus.SCHEDULED
    )
    trip = models.OneToOneField(
        Trip, null=True, blank=True, on_delete=models.SET_NULL, related_name="schedule"
    )
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["scheduled_for"]
        indexes = [
            # The dispatcher only ever scans rides still waiting to go out.
            models.Index(
                fields=["scheduled_for"],
                name="scheduled_ride_due_idx",
                condition=Q(status="SCHEDULED"),
            )
        ]

    def __str__(self) -> str:
        return f"{self.rider_id} at {self.scheduled_for:%Y-%m-%d %H:%M}"


class FareSplitStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Waiting for payment"
    PAID = "PAID", "Paid"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"


class FareSplit(models.Model):
    """One friend's share of a ride the rider paid for. Paying it reimburses the rider's wallet."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="splits")
    friend = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="split_requests"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=FareSplitStatus.choices, default=FareSplitStatus.REQUESTED
    )
    payment_method = models.CharField(max_length=6, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "friend"], name="fare_split_friend_once"),
        ]

    def __str__(self) -> str:
        return f"{self.trip_id} split with {self.friend_id} ({self.status})"


class LostItemStatus(models.TextChoices):
    REPORTED = "REPORTED", "Waiting for the driver"
    FOUND = "FOUND", "Driver found it"
    NOT_FOUND = "NOT_FOUND", "Driver couldn't find it"
    RETURNED = "RETURNED", "Returned"


class LostItemReport(models.Model):
    """ "I left something in the car": the driver checks and answers; calls stay open for 24 h."""

    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name="lost_item")
    description = models.CharField(max_length=300)
    status = models.CharField(
        max_length=9, choices=LostItemStatus.choices, default=LostItemStatus.REPORTED
    )
    driver_note = models.CharField(max_length=300, blank=True)
    ticket = models.ForeignKey(
        "support.SupportTicket", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.trip_id}: {self.description[:30]} ({self.status})"


class RideCheckKind(models.TextChoices):
    LONG_STOP = "LONG_STOP", "The car hasn't moved for a while"
    OFF_ROUTE = "OFF_ROUTE", "The car is far from the route"
    RUNNING_LATE = "RUNNING_LATE", "The trip is taking much longer than expected"
    SIGNAL_LOST = "SIGNAL_LOST", "We lost the car's location"


class RideCheckStatus(models.TextChoices):
    OPEN = "OPEN", "Waiting for the rider"
    OK = "OK", "Rider is OK"
    HELP = "HELP", "Rider asked for help"
    ESCALATED = "ESCALATED", "No answer: sent to the safety team"
    CLOSED = "CLOSED", "Trip ended normally before an answer"


class RideCheck(models.Model):
    """ "Is everything OK?": raised automatically when a trip looks wrong (see rides.safety)."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="ride_checks")
    kind = models.CharField(max_length=12, choices=RideCheckKind.choices)
    status = models.CharField(
        max_length=9, choices=RideCheckStatus.choices, default=RideCheckStatus.OPEN
    )
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    driver_ok = models.BooleanField(null=True, blank=True)
    incident = models.ForeignKey(
        "support.SafetyIncident", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "kind"], name="ride_check_once_per_kind"),
        ]
        indexes = [
            models.Index(
                fields=["created_at"], condition=Q(status="OPEN"), name="ride_check_open_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trip_id} {self.kind} ({self.status})"


class ParcelDelivery(models.Model):
    """The parcel on a PARCEL trip: who receives it, what it is, and the delivery code the
    recipient gives the driver at the door (the delivery can't be completed without it)."""

    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name="parcel")
    recipient_name = models.CharField(max_length=80)
    recipient_phone = models.CharField(max_length=15)
    category = models.CharField(max_length=12, choices=ParcelCategory.choices)
    weight_kg = models.DecimalField(max_digits=4, decimal_places=1)
    instructions = models.CharField(max_length=200, blank=True)
    delivery_code = models.CharField(max_length=4)
    code_attempts = models.PositiveSmallIntegerField(default=0)
    recipient_notified_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.trip_id} → {self.recipient_name}"


# --- Guardian mode: emergency location sharing -----------------------------------------------


class ShareTrigger(models.TextChoices):
    SOS = "SOS", "SOS pressed"
    SHAKE = "SHAKE", "Phone shaken"
    RIDE_CHECK = "RIDE_CHECK", "Ride Check alert"
    NO_ANSWER = "NO_ANSWER", "Ride Check not answered"
    MANUAL = "MANUAL", "Shared by the rider"


class LocationSource(models.TextChoices):
    PHONE = "PHONE", "Rider's phone"
    CAR = "CAR", "The car (driver's app)"


class EmergencyShare(models.Model):
    """While something is wrong, the rider's live location goes to their trusted contacts (an
    SMS with a map pin and a live link), until the rider taps "I'm safe" or it times out."""

    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="emergency_shares"
    )
    trip = models.ForeignKey(
        Trip, null=True, blank=True, on_delete=models.SET_NULL, related_name="emergency_shares"
    )
    triggers = ArrayField(models.CharField(max_length=10), default=list)
    detail = models.CharField(max_length=200, blank=True)
    token = models.CharField(max_length=32, unique=True)
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.CharField(max_length=8, blank=True)  # RIDER, OPS, EXPIRED
    last_lat = models.FloatField(null=True, blank=True)
    last_lng = models.FloatField(null=True, blank=True)
    last_source = models.CharField(max_length=5, choices=LocationSource.choices, blank=True)
    last_at = models.DateTimeField(null=True, blank=True)
    contacts_alerted = models.PositiveSmallIntegerField(default=0)
    reminders_sent = models.PositiveSmallIntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rider"],
                condition=Q(ended_at__isnull=True),
                name="one_open_share_per_rider",
            )
        ]

    def __str__(self) -> str:
        return f"{self.rider_id} {self.triggers}"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None
