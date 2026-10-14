from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.audit.mixins import AuditedModel
from apps.core.models import LatitudeField, LongitudeField, TimeStampedModel
from apps.core.validators import phone_validator


class RiderProfile(AuditedModel, TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rider_profile"
    )
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("5.00"))
    rating_count = models.PositiveIntegerField(default=0)
    completed_trips = models.PositiveIntegerField(default=0)
    referral_code = models.CharField(max_length=12, unique=True)
    referred_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals"
    )
    # Set once both sides have been paid the referral bonus (after this rider's first trip).
    referral_rewarded_at = models.DateTimeField(null=True, blank=True)
    # Ride preferences pre-selected when booking (see rides.models.RidePreference).
    default_preferences = ArrayField(models.CharField(max_length=12), default=list, blank=True)
    # Drivers this rider liked: offered their rides first when nearby.
    favourite_drivers = models.ManyToManyField(
        "drivers.DriverProfile", blank=True, related_name="favourited_by"
    )
    default_payment_method = models.CharField(max_length=10, default="UPI")
    emergency_contact_name = models.CharField(max_length=80, blank=True)
    emergency_contact_phone = models.CharField(
        max_length=15, blank=True, validators=[phone_validator]
    )
    # Eco score: points from CO2 saved (100 points = ₹10 in the wallet).
    eco_points = models.PositiveIntegerField(default=0)
    co2_saved_g = models.PositiveBigIntegerField(default=0)
    # Night Safe mode: stricter Ride Checks, auto-share and drop control from 10 pm to 6 am.
    night_safety = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return str(self.user)

    @property
    def name(self) -> str:
        return self.user.get_full_name() or self.user.email


class PlaceLabel(models.TextChoices):
    HOME = "HOME", "Home"
    WORK = "WORK", "Work"
    OTHER = "OTHER", "Other"


class SavedPlace(models.Model):
    rider = models.ForeignKey(RiderProfile, on_delete=models.CASCADE, related_name="saved_places")
    label = models.CharField(max_length=5, choices=PlaceLabel.choices, default=PlaceLabel.OTHER)
    name = models.CharField(max_length=80)
    address = models.CharField(max_length=255, blank=True)
    lat = LatitudeField()
    lng = LongitudeField()

    class Meta:
        ordering = ["label", "name"]
        constraints = [
            # One Home and one Work per rider; any number of other places.
            models.UniqueConstraint(
                fields=["rider", "label"],
                condition=~Q(label="OTHER"),
                name="saved_place_one_home_one_work",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_label_display()}: {self.name}"


class ShareMode(models.TextChoices):
    ALWAYS = "ALWAYS", "Every ride"
    NIGHT = "NIGHT", "Night rides"
    NEVER = "NEVER", "Only when I share"


class TrustedContact(models.Model):
    """Someone who gets the rider's live trip link (and Ride Check alerts)."""

    rider = models.ForeignKey(RiderProfile, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    share_mode = models.CharField(max_length=6, choices=ShareMode.choices, default=ShareMode.NIGHT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["rider", "phone"], name="trusted_contact_once"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"


class ProfileKind(models.TextChoices):
    FAMILY = "FAMILY", "Family"
    BUSINESS = "BUSINESS", "Business"


class PaymentProfile(models.Model):
    """One payer for several riders: a family head paying for family members, or a company
    paying for employees' work trips (see riders.profiles)."""

    kind = models.CharField(max_length=8, choices=ProfileKind.choices)
    name = models.CharField(max_length=80)
    owner = models.ForeignKey(RiderProfile, on_delete=models.CASCADE, related_name="owned_profiles")
    gstin = models.CharField(max_length=15, blank=True)
    # Business only: how far the company's balance may go below zero (settled monthly).
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.name}"


class MemberStatus(models.TextChoices):
    INVITED = "INVITED", "Invited"
    ACTIVE = "ACTIVE", "Active"
    DECLINED = "DECLINED", "Declined"
    REMOVED = "REMOVED", "Removed"


class ProfileMember(models.Model):
    profile = models.ForeignKey(PaymentProfile, on_delete=models.CASCADE, related_name="members")
    rider = models.ForeignKey(RiderProfile, on_delete=models.CASCADE, related_name="memberships")
    status = models.CharField(
        max_length=8, choices=MemberStatus.choices, default=MemberStatus.INVITED
    )
    # Monthly spending limit on this profile (blank = no limit).
    monthly_limit = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["invited_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "rider"], name="profile_member_once"),
        ]

    def __str__(self) -> str:
        return f"{self.rider_id} in {self.profile_id} ({self.status})"
