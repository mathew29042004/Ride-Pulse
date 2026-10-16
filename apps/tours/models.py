"""Tour packages: day trips and short tours to famous places, at a fixed price per car, with a
driver assigned ahead and the itinerary followed stop by stop."""

from django.db import models
from django.db.models import Q


class TourCategory(models.TextChoices):
    HERITAGE = "HERITAGE", "Heritage"
    PILGRIMAGE = "PILGRIMAGE", "Pilgrimage"
    NATURE = "NATURE", "Nature & waterfalls"
    BEACH = "BEACH", "Beaches"
    HILLS = "HILLS", "Hill stations"
    CITY = "CITY", "City tours"


class TourPackage(models.Model):
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="tours")
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=80)
    tagline = models.CharField(max_length=160)
    category = models.CharField(max_length=10, choices=TourCategory.choices)
    days = models.PositiveSmallIntegerField(default=1)
    start_time = models.TimeField()  # suggested departure; the rider can move it
    # Seasonal or promotional adjustment on the computed price, set by ops (-30 … +50).
    price_adjust_percent = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    rating_sum = models.PositiveIntegerField(default=0)
    rating_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["city__name", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def rating(self) -> float | None:
        return round(self.rating_sum / self.rating_count, 2) if self.rating_count else None


class TourStop(models.Model):
    package = models.ForeignKey(TourPackage, on_delete=models.CASCADE, related_name="stops")
    order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=80)
    lat = models.FloatField()
    lng = models.FloatField()
    minutes = models.PositiveSmallIntegerField()  # time spent at the place
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["package", "order"]
        constraints = [
            models.UniqueConstraint(fields=["package", "order"], name="tour_stop_order_unique")
        ]

    def __str__(self) -> str:
        return f"{self.package_id} #{self.order} {self.name}"


class BookingStatus(models.TextChoices):
    BOOKED = "BOOKED", "Booked (finding your driver)"
    ASSIGNED = "ASSIGNED", "Driver assigned"
    STARTED = "STARTED", "On the tour"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class TourBooking(models.Model):
    reference = models.CharField(max_length=20, unique=True)
    package = models.ForeignKey(TourPackage, on_delete=models.PROTECT, related_name="bookings")
    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="tour_bookings"
    )
    ride_type = models.ForeignKey("pricing.RideType", on_delete=models.PROTECT, related_name="+")
    depart_at = models.DateTimeField(db_index=True)
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    pickup_address = models.CharField(max_length=255, blank=True)
    group_size = models.PositiveSmallIntegerField(default=1)
    payment_method = models.CharField(max_length=8)
    # The price is fixed when booking (the fare breakdown is kept as it was quoted).
    fare = models.JSONField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=9, choices=BookingStatus.choices, default=BookingStatus.BOOKED
    )
    driver = models.ForeignKey(
        "drivers.DriverProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tour_bookings",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.JSONField(default=list, blank=True)  # driver ids who said no
    trip = models.OneToOneField(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="tour_booking"
    )
    # {"1": {"arrived": iso, "left": iso}, …} as the driver reaches and leaves each stop
    progress = models.JSONField(default=dict, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=8, blank=True)
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-depart_at"]
        indexes = [models.Index(fields=["status", "depart_at"], name="tour_booking_due_idx")]
        constraints = [
            # A driver can't be booked for two tours leaving the same day (checked in code by
            # date; this stops the same booking being double-assigned).
            models.CheckConstraint(
                condition=Q(group_size__gte=1) & Q(group_size__lte=8), name="tour_group_size"
            ),
        ]

    def __str__(self) -> str:
        return self.reference
