"""Driver business: weekly statements with TDS, fleet owners, vehicle upkeep, EV charging,
incentive quests and the airport queue."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

# --- Weekly statements -----------------------------------------------------------------------


class DriverStatement(models.Model):
    """One week of a driver's business: what riders paid, what the driver earned, the tax
    withheld (TDS) and what was paid out."""

    number = models.CharField(max_length=24, unique=True)
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="statements"
    )
    week_start = models.DateField()
    week_end = models.DateField()
    trips = models.PositiveIntegerField()
    gross_fares = models.DecimalField(max_digits=12, decimal_places=2)
    commission = models.DecimalField(max_digits=12, decimal_places=2)
    trip_earnings = models.DecimalField(max_digits=12, decimal_places=2)
    tips = models.DecimalField(max_digits=12, decimal_places=2)
    bonuses = models.DecimalField(max_digits=12, decimal_places=2)
    cancellation_fees = models.DecimalField(max_digits=12, decimal_places=2)
    fleet_share = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_collected = models.DecimalField(max_digits=12, decimal_places=2)
    distance_km = models.DecimalField(max_digits=10, decimal_places=2)
    pan_on_file = models.BooleanField()
    tds_rate = models.DecimalField(max_digits=6, decimal_places=4)
    tds_amount = models.DecimalField(max_digits=12, decimal_places=2)
    net_earnings = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(fields=["driver", "week_start"], name="one_statement_a_week")
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.driver_id} {self.week_start}"


# --- Fleet owners ----------------------------------------------------------------------------


class FleetOwner(TimeStampedModel):
    """A business partner who owns vehicles and employs drivers. They keep a share of their
    drivers' trip earnings (paid through the ledger on every trip)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fleet_owner"
    )
    company_name = models.CharField(max_length=120)
    city = models.ForeignKey("geo.City", on_delete=models.PROTECT, related_name="fleet_owners")
    gstin = models.CharField(max_length=15, blank=True)
    share_percent = models.DecimalField(max_digits=5, decimal_places=2)
    account_manager = models.ForeignKey(
        "accounts.StaffProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fleet_accounts",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company_name"]

    def __str__(self) -> str:
        return self.company_name


class FleetMembership(models.Model):
    owner = models.ForeignKey(FleetOwner, on_delete=models.CASCADE, related_name="memberships")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="fleet_memberships"
    )
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["driver"], condition=Q(left_at__isnull=True), name="one_fleet_per_driver"
            )
        ]

    def __str__(self) -> str:
        return f"{self.owner_id} ← {self.driver_id}"


# --- Vehicle upkeep --------------------------------------------------------------------------


class ServiceKind(models.TextChoices):
    ROUTINE = "ROUTINE", "Routine service"
    REPAIR = "REPAIR", "Repair"
    TYRES = "TYRES", "Tyres"
    BATTERY = "BATTERY", "Battery"
    ACCIDENT = "ACCIDENT", "Accident repair"
    INSPECTION = "INSPECTION", "Fitness inspection"


class ServiceRecord(models.Model):
    """One visit to a workshop: what was done, the parts, what it cost, and the invoice."""

    vehicle = models.ForeignKey(
        "drivers.Vehicle", on_delete=models.CASCADE, related_name="service_records"
    )
    kind = models.CharField(max_length=10, choices=ServiceKind.choices, default=ServiceKind.ROUTINE)
    odometer_km = models.PositiveIntegerField()
    serviced_on = models.DateField()
    workshop = models.CharField(max_length=120, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    # [{"name": "Brake pads", "cost": "1800.00"}, …]
    parts = models.JSONField(default=list, blank=True)
    parts_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    labour_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    invoice_number = models.CharField(max_length=40, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-serviced_on", "-pk"]

    def __str__(self) -> str:
        return f"{self.vehicle_id} @ {self.odometer_km} km"

    @property
    def total_cost(self):
        return self.parts_cost + self.labour_cost


class VehicleInspection(models.Model):
    """The driver's pre-shift walk-round: each checklist item passed or failed."""

    vehicle = models.ForeignKey(
        "drivers.Vehicle", on_delete=models.CASCADE, related_name="inspections"
    )
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="inspections"
    )
    inspected_on = models.DateField(db_index=True)
    items = models.JSONField(default=dict)  # {"brakes": true, "tyres": false, …}
    passed = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.vehicle_id} {self.inspected_on} {'pass' if self.passed else 'fail'}"


class IssueSource(models.TextChoices):
    DRIVER = "DRIVER", "Driver"
    RIDER = "RIDER", "Rider"
    INSPECTION = "INSPECTION", "Daily check"
    OWNER = "OWNER", "Fleet owner"
    OPS = "OPS", "Operations"


class IssueKind(models.TextChoices):
    BREAKDOWN = "BREAKDOWN", "Breakdown"
    ACCIDENT = "ACCIDENT", "Accident"
    BRAKES = "BRAKES", "Brakes"
    TYRES = "TYRES", "Tyres"
    LIGHTS = "LIGHTS", "Lights"
    SEATBELTS = "SEATBELTS", "Seat belts"
    AC = "AC", "Air conditioning"
    CLEANLINESS = "CLEANLINESS", "Cleanliness"
    OTHER = "OTHER", "Other"


class IssueSeverity(models.TextChoices):
    MINOR = "MINOR", "Minor (fix soon)"
    MAJOR = "MAJOR", "Major (fix this week)"
    CRITICAL = "CRITICAL", "Critical (unsafe: off the road)"


class IssueStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_REPAIR = "IN_REPAIR", "In repair"
    RESOLVED = "RESOLVED", "Resolved"


class VehicleIssue(models.Model):
    """A fault: a breakdown, a failed check item, or a rider's report. Critical ones take the
    vehicle off the road until a repair is logged."""

    vehicle = models.ForeignKey("drivers.Vehicle", on_delete=models.CASCADE, related_name="issues")
    source = models.CharField(max_length=10, choices=IssueSource.choices)
    kind = models.CharField(max_length=11, choices=IssueKind.choices)
    severity = models.CharField(max_length=8, choices=IssueSeverity.choices)
    description = models.CharField(max_length=300, blank=True)
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=9, choices=IssueStatus.choices, default=IssueStatus.OPEN)
    repair = models.ForeignKey(
        ServiceRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="fixed"
    )
    opened_at = models.DateTimeField(db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [models.Index(fields=["vehicle", "status"], name="vehicle_issue_open_idx")]

    def __str__(self) -> str:
        return f"{self.vehicle_id} {self.kind} {self.status}"


# --- EV charging -----------------------------------------------------------------------------


class ChargingStation(models.Model):
    city = models.ForeignKey("geo.City", on_delete=models.CASCADE, related_name="chargers")
    name = models.CharField(max_length=120)
    operator = models.CharField(max_length=60)
    lat = models.FloatField()
    lng = models.FloatField()
    power_kw = models.PositiveSmallIntegerField()
    connectors = models.PositiveSmallIntegerField()
    two_wheeler = models.BooleanField(default=True)
    four_wheeler = models.BooleanField(default=True)
    price_per_kwh = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        ordering = ["city", "name"]

    def __str__(self) -> str:
        return self.name


# --- Incentive quests ------------------------------------------------------------------------


class QuestStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    LIVE = "LIVE", "Live"
    ENDED = "ENDED", "Ended"
    CANCELLED = "CANCELLED", "Cancelled"


class Quest(TimeStampedModel):
    """ "20 trips this weekend = ₹500": created by ops without code, paid automatically."""

    number = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.CASCADE, related_name="quests"
    )  # blank = every city in the state
    state = models.CharField(max_length=60, blank=True)
    ride_types = models.ManyToManyField("pricing.RideType", blank=True, related_name="+")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    # Tiers: [[trips, reward], ...] in increasing order, e.g. [[10, 150], [20, 400]].
    tiers = models.JSONField()
    peak_hours_only = models.BooleanField(default=False)  # 7-10 am and 5-9 pm local
    min_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2)
    spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=QuestStatus.choices, default=QuestStatus.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self) -> str:
        return self.name


class QuestProgress(models.Model):
    quest = models.ForeignKey(Quest, on_delete=models.CASCADE, related_name="progress")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="quest_progress"
    )
    trips = models.PositiveIntegerField(default=0)
    tiers_paid = models.PositiveSmallIntegerField(default=0)
    earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["quest", "driver"], name="one_progress_per_quest")
        ]

    def __str__(self) -> str:
        return f"{self.quest_id} {self.driver_id}: {self.trips}"


# --- Airport queue ---------------------------------------------------------------------------


class QueueStatus(models.TextChoices):
    WAITING = "WAITING", "Waiting"
    DISPATCHED = "DISPATCHED", "Got a trip"
    LEFT = "LEFT", "Left the queue"


class AirportQueueEntry(models.Model):
    zone = models.ForeignKey("geo.Zone", on_delete=models.CASCADE, related_name="queue")
    driver = models.ForeignKey(
        "drivers.DriverProfile", on_delete=models.CASCADE, related_name="airport_queue"
    )
    status = models.CharField(
        max_length=10, choices=QueueStatus.choices, default=QueueStatus.WAITING
    )
    joined_at = models.DateTimeField()
    outside_since = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    trip = models.ForeignKey(
        "rides.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["joined_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver"], condition=Q(status="WAITING"), name="one_queue_spot_per_driver"
            )
        ]

    def __str__(self) -> str:
        return f"{self.zone_id} {self.driver_id} {self.status}"
