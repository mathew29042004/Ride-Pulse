from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from .roles import capabilities_for


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrator"
    REGIONAL_MANAGER = "REGIONAL_MANAGER", "Regional manager"
    OPS_MANAGER = "OPS_MANAGER", "City operations manager"
    ASSOC_RIDES = "ASSOC_RIDES", "Associate manager · Rides"
    ASSOC_SUPPORT = "ASSOC_SUPPORT", "Associate manager · Support"
    ASSOC_MAINTENANCE = "ASSOC_MAINTENANCE", "Associate manager · Fleet & maintenance"
    ASSOC_INTERCITY = "ASSOC_INTERCITY", "Associate manager · Intercity & rentals"
    ASSOC_PARCELS = "ASSOC_PARCELS", "Associate manager · Parcels"
    SUPPORT_LEAD = "SUPPORT_LEAD", "Support team lead"
    SUPPORT_AGENT = "SUPPORT_AGENT", "Support agent"
    FLEET_EXECUTIVE = "FLEET_EXECUTIVE", "Fleet executive"
    DRIVER = "DRIVER", "Driver"
    RIDER = "RIDER", "Rider"
    FLEET_OWNER = "FLEET_OWNER", "Fleet owner (partner)"


# Partners and customers: they only ever see their own records.
END_USER_ROLES = (Role.RIDER, Role.DRIVER, Role.FLEET_OWNER)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.ADMIN)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RIDER)
    phone = models.CharField(max_length=15, blank=True)
    # App language (en, ta, hi): chat messages are translated into it (rides.translate).
    language = models.CharField(
        max_length=2,
        choices=[
            ("en", "English"),
            ("ta", "Tamil"),
            ("hi", "Hindi"),
            ("ml", "Malayalam"),
            ("kn", "Kannada"),
            ("te", "Telugu"),
        ],
        default="en",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]
        indexes = [models.Index(fields=["role", "is_active"], name="user_role_active_idx")]
        constraints = [
            # A phone number signs in to exactly one account (phone OTP login).
            models.UniqueConstraint(
                fields=["phone"], condition=~models.Q(phone=""), name="user_phone_unique"
            )
        ]

    def __str__(self) -> str:
        return self.get_full_name() or self.email

    @property
    def is_rider(self) -> bool:
        return self.role == Role.RIDER

    @property
    def is_driver(self) -> bool:
        return self.role == Role.DRIVER

    @property
    def is_end_user(self) -> bool:
        return self.role in END_USER_ROLES

    @property
    def is_staff_member(self) -> bool:
        return not self.is_end_user

    @property
    def capabilities(self) -> frozenset[str]:
        return capabilities_for(self.role) if self.is_active else frozenset()

    def has_capability(self, capability: str) -> bool:
        return self.is_active and (self.is_superuser or capability in self.capabilities)

    @property
    def initials(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return "".join(p[0] for p in parts).upper() or self.email[:2].upper()


class PhoneOTP(models.Model):
    """A one-time login code sent by SMS. Only a keyed hash of the code is stored."""

    phone = models.CharField(max_length=10)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["phone", "created_at"], name="otp_phone_created_idx")]

    def __str__(self) -> str:
        return f"OTP for {self.phone[:2]}******{self.phone[-2:]}"


class Department(models.TextChoices):
    LEADERSHIP = "LEADERSHIP", "Leadership"
    OPERATIONS = "OPERATIONS", "City operations"
    RIDES = "RIDES", "Rides"
    SUPPORT = "SUPPORT", "Customer support"
    MAINTENANCE = "MAINTENANCE", "Fleet & maintenance"
    INTERCITY = "INTERCITY", "Intercity & rentals"
    PARCELS = "PARCELS", "Parcels"


class StaffProfile(models.Model):
    """An employee's place in the organisation: title, department, where they work and who they
    report to (``reports_to`` builds the org chart from regional managers down to the fleet
    executives who look after driver partners)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    employee_id = models.CharField(max_length=12, unique=True)
    title = models.CharField(max_length=80)
    department = models.CharField(max_length=12, choices=Department.choices)
    state = models.CharField(max_length=60, blank=True)
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    reports_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports"
    )
    joined_on = models.DateField()

    class Meta:
        ordering = ["employee_id"]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.user.get_full_name()} ({self.title})"


from .two_factor import TwoFactor  # noqa: E402,F401  (registers the model)
