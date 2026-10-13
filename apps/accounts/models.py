from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from .roles import capabilities_for


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrator"
    OPS_MANAGER = "OPS_MANAGER", "Operations manager"
    SUPPORT_AGENT = "SUPPORT_AGENT", "Support agent"
    DRIVER = "DRIVER", "Driver"
    RIDER = "RIDER", "Rider"


END_USER_ROLES = (Role.RIDER, Role.DRIVER)


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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]
        indexes = [models.Index(fields=["role", "is_active"], name="user_role_active_idx")]

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
