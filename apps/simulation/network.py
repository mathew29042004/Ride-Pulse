"""Grow the demo network: drivers and riders in every city, and the staff organisation.

Idempotent and additive (no flush): cities are topped up to their target number of drivers,
bot riders up to a total, the org chart is created once, and every driver gets a fleet
executive in their city. Used by ``manage.py grow_network`` and at the end of ``seed_demo``.
"""

import contextlib
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Department, Role, StaffProfile
from apps.core.exceptions import DomainError
from apps.drivers import services as drivers_svc
from apps.drivers.models import DriverProfile, OnboardingStatus, Vehicle
from apps.geo.models import City
from apps.notifications import services as notifications
from apps.pricing.models import RideType
from apps.realtime import broadcast
from apps.riders.models import RiderProfile

from .seed import DEMO_PASSWORD, Seeder

# Bigger cities get more drivers.
METROS = {"chennai": 70, "bengaluru": 70}
TIER_ONE = {
    "coimbatore": 34,
    "kochi": 34,
    "visakhapatnam": 32,
    "thiruvananthapuram": 28,
    "vijayawada": 28,
    "madurai": 28,
    "mysuru": 26,
    "mangaluru": 22,
    "kozhikode": 22,
    "tiruchirappalli": 22,
    "tirupati": 20,
    "hubballi-dharwad": 20,
}
OTHER_CITY_DRIVERS = 12
# Every city can serve every ride type: at least this many approved drivers of each vehicle.
MIN_PER_VEHICLE = 3
VEHICLE_TYPES = ["BIKE", "AUTO", "MINI", "SEDAN", "SUV"]
BOT_RIDERS_TARGET = 900
DRIVERS_PER_FLEET_EXECUTIVE = 15

STATES = ["Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh"]
STATE_HQ = {
    "Tamil Nadu": "chennai",
    "Kerala": "kochi",
    "Karnataka": "bengaluru",
    "Andhra Pradesh": "visakhapatnam",
}
ASSOCIATES = [
    (Role.ASSOC_RIDES, Department.RIDES, "Associate Manager, Rides"),
    (Role.ASSOC_SUPPORT, Department.SUPPORT, "Associate Manager, Customer Support"),
    (Role.ASSOC_MAINTENANCE, Department.MAINTENANCE, "Associate Manager, Fleet & Maintenance"),
    (Role.ASSOC_INTERCITY, Department.INTERCITY, "Associate Manager, Intercity & Rentals"),
    (Role.ASSOC_PARCELS, Department.PARCELS, "Associate Manager, Parcels"),
]
# Demo logins for the new roles (Tamil Nadu), with the usual demo password.
DEMO_STAFF = {
    Role.REGIONAL_MANAGER: ("regional@ridepulse.dev", "Lakshmi", "Venkatesan"),
    Role.ASSOC_RIDES: ("rides@ridepulse.dev", "Karthikeyan", "Subramanian"),
    Role.ASSOC_SUPPORT: ("supportlead@ridepulse.dev", "Nithya", "Ramesh"),
    Role.ASSOC_MAINTENANCE: ("fleet@ridepulse.dev", "Senthil", "Kumar"),
    Role.ASSOC_INTERCITY: ("intercity@ridepulse.dev", "Anitha", "Prakash"),
    Role.ASSOC_PARCELS: ("parcels@ridepulse.dev", "Vignesh", "Balaji"),
    Role.FLEET_EXECUTIVE: ("fleetexec@ridepulse.dev", "Gokul", "Murugan"),
}


def driver_target(slug: str) -> int:
    return METROS.get(slug) or TIER_ONE.get(slug) or OTHER_CITY_DRIVERS


class NetworkBuilder:
    def __init__(self, *, seed: int = 7, log: Callable[[str], None] = print):
        self.log = log
        self.seeder = Seeder(seed=seed, log=log)
        self.rng, self.fake = self.seeder.rng, self.seeder.fake
        self.today = timezone.localdate()
        self.next_employee = StaffProfile.objects.count() + 1
        self.stats: dict[str, int] = {}

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    # --- Staff ----------------------------------------------------------------------------

    def _employee(
        self,
        role: str,
        department: str,
        title: str,
        *,
        city: City | None,
        state: str,
        reports_to: StaffProfile | None,
        email: str | None = None,
        first: str | None = None,
        last: str | None = None,
        user=None,
    ) -> StaffProfile:
        User = get_user_model()
        if user is None:
            if email and User.objects.filter(email=email).exists():
                user = User.objects.get(email=email)
            else:
                first = first or self.fake.first_name()
                last = last or self.fake.last_name()
                user = User.objects.create_user(
                    email or self.seeder._email(first, last, "staff.ridepulse.dev"),
                    DEMO_PASSWORD if email else None,
                    first_name=first,
                    last_name=last,
                    role=role,
                    phone=self.seeder._phone(),
                )
        profile, _ = StaffProfile.objects.get_or_create(
            user=user,
            defaults={
                "employee_id": f"RP{self.next_employee:05d}",
                "title": title,
                "department": department,
                "state": state,
                "city": city,
                "reports_to": reports_to,
                "joined_on": self.today - timedelta(days=self.rng.randrange(30, 1500)),
            },
        )
        self.next_employee += 1
        self.count(f"staff:{role}")
        return profile

    def build_org(self, cities: dict[str, City]) -> None:
        if StaffProfile.objects.exists():
            self.log("Staff organisation already exists; skipping.")
            return
        User = get_user_model()
        self.seeder.used_emails |= set(User.objects.values_list("email", flat=True))
        admin = (
            User.objects.filter(email="admin@ridepulse.dev").first()
            or User.objects.filter(is_superuser=True).order_by("pk").first()
        )
        head = (
            self._employee(
                Role.ADMIN,
                Department.LEADERSHIP,
                "Head of Operations, South India",
                city=cities.get("chennai"),
                state="",
                reports_to=None,
                user=admin,
            )
            if admin
            else None
        )
        existing = {u.email: u for u in User.objects.filter(email__endswith="@ridepulse.dev")}
        for state in STATES:
            hq = cities[STATE_HQ[state]]
            demo = state == "Tamil Nadu"
            email, first, last = DEMO_STAFF[Role.REGIONAL_MANAGER] if demo else (None, None, None)
            regional = self._employee(
                Role.REGIONAL_MANAGER,
                Department.LEADERSHIP,
                f"Regional Manager, {state}",
                city=hq,
                state=state,
                reports_to=head,
                email=email,
                first=first,
                last=last,
            )
            for role, department, title in ASSOCIATES:
                email, first, last = DEMO_STAFF[role] if demo else (None, None, None)
                self._employee(
                    role,
                    department,
                    f"{title} ({state})",
                    city=hq,
                    state=state,
                    reports_to=regional,
                    email=email,
                    first=first,
                    last=last,
                )
            for _slug, city in cities.items():
                if city.state != state:
                    continue
                self._city_team(city, regional, existing)

    def _city_team(self, city: City, regional: StaffProfile, existing: dict) -> None:
        manager_user = {"chennai": "ops@ridepulse.dev", "bengaluru": "ops2@ridepulse.dev"}.get(
            city.slug
        )
        manager = self._employee(
            Role.OPS_MANAGER,
            Department.OPERATIONS,
            f"City Operations Manager, {city.name}",
            city=city,
            state=city.state,
            reports_to=regional,
            user=existing.get(manager_user),
        )
        target = driver_target(city.slug)
        agents = max(1, target // 12)
        lead = None
        if agents >= 2:
            lead = self._employee(
                Role.SUPPORT_LEAD,
                Department.SUPPORT,
                f"Support Team Lead, {city.name}",
                city=city,
                state=city.state,
                reports_to=manager,
            )
        demo_agents = (
            [existing.get("support@ridepulse.dev"), existing.get("support2@ridepulse.dev")]
            if city.slug == "chennai"
            else []
        )
        for i in range(agents):
            user = demo_agents[i] if i < len(demo_agents) else None
            self._employee(
                Role.SUPPORT_AGENT,
                Department.SUPPORT,
                f"Support Agent, {city.name}",
                city=city,
                state=city.state,
                reports_to=lead or manager,
                user=user,
            )
        for i in range(max(1, -(-target // DRIVERS_PER_FLEET_EXECUTIVE))):
            demo = city.slug == "chennai" and i == 0
            email, first, last = DEMO_STAFF[Role.FLEET_EXECUTIVE] if demo else (None, None, None)
            self._employee(
                Role.FLEET_EXECUTIVE,
                Department.MAINTENANCE,
                f"Fleet Executive, {city.name}",
                city=city,
                state=city.state,
                reports_to=manager,
                email=email,
                first=first,
                last=last,
            )

    def assign_fleet_executives(self) -> None:
        for city in City.objects.all():
            executives = list(
                StaffProfile.objects.filter(city=city, user__role=Role.FLEET_EXECUTIVE).order_by(
                    "employee_id"
                )
            )
            if not executives:
                continue
            unassigned = DriverProfile.objects.filter(city=city, fleet_executive__isnull=True)
            for i, pk in enumerate(unassigned.values_list("pk", flat=True)):
                DriverProfile.objects.filter(pk=pk).update(
                    fleet_executive=executives[i % len(executives)]
                )
                self.count("drivers_assigned")

    # --- Drivers and riders -------------------------------------------------------------------

    def grow_drivers(self, cities: dict[str, City]) -> None:
        User = get_user_model()
        seeder = self.seeder
        seeder.ride_types = {rt.code: rt for rt in RideType.objects.all()}
        seeder.ops_manager = User.objects.filter(email="ops@ridepulse.dev").first() or (
            User.objects.filter(is_superuser=True).first()
        )
        seeder.used_plates |= set(Vehicle.objects.values_list("registration_number", flat=True))
        seeder.used_emails |= set(User.objects.values_list("email", flat=True))
        seeder.used_phones |= set(User.objects.exclude(phone="").values_list("phone", flat=True))
        for slug, city in cities.items():
            have = DriverProfile.objects.filter(city=city).count()
            need = driver_target(slug) - have
            if need <= 0:
                continue
            for i in range(need):
                documents = "approved" if i < need - max(1, need // 10) else "submitted"
                with transaction.atomic():
                    seeder._add_driver(city, documents=documents)
            self.count("drivers_added", need)
            self.log(f"  {city.name}: +{need} drivers")

    def fill_vehicle_gaps(self, cities: dict[str, City]) -> None:
        """Top up each city to MIN_PER_VEHICLE approved drivers of every vehicle type."""
        from django.db.models import Count

        have = {
            (row["city__slug"], row["vehicles__ride_type__code"]): row["n"]
            for row in DriverProfile.objects.filter(
                onboarding_status=OnboardingStatus.APPROVED, vehicles__is_active=True
            )
            .values("city__slug", "vehicles__ride_type__code")
            .annotate(n=Count("id"))
        }
        for slug, city in cities.items():
            for code in VEHICLE_TYPES:
                for _ in range(max(0, MIN_PER_VEHICLE - have.get((slug, code), 0))):
                    with transaction.atomic():
                        self.seeder._add_driver(city, ride_type=code)
                    self.count("gap_drivers_added")

    def grow_riders(self) -> None:
        from apps.payments import services as payments
        from apps.riders.services import register_rider

        have = RiderProfile.objects.filter(user__email__endswith="@example.com").count()
        for _ in range(max(0, BOT_RIDERS_TARGET - have)):
            first, last = self.fake.first_name(), self.fake.last_name()
            rider = register_rider(
                email=self.seeder._email(first, last, "example.com"),
                password=None,
                first_name=first,
                last_name=last,
                phone=self.seeder._phone(),
            )
            if self.rng.random() < 0.4:
                payments.top_up(
                    rider.user,
                    Decimal(self.rng.choice([200, 500, 1000])),
                    method="UPI",
                    payer_reference="seed@upi",
                )
            self.count("riders_added")

    def run(self) -> dict:
        cities = {c.slug: c for c in City.objects.filter(is_active=True)}
        with notifications.muted(), broadcast.muted():
            self.log(f"Growing the network across {len(cities)} cities…")
            self.grow_drivers(cities)
            self.fill_vehicle_gaps(cities)
            self.grow_riders()
            self.build_org(cities)
            self.assign_fleet_executives()
            # Seeded drivers go home at the end, like the main seeder does.
            for driver in DriverProfile.objects.exclude(availability="OFFLINE").filter(
                user__email__endswith="@drivers.example.com"
            ):
                with contextlib.suppress(DomainError):
                    drivers_svc.go_offline(driver)
        from apps.pricing import coverage

        changes = coverage.sync()
        self.stats["ride_types_paused"] = len(changes["paused"])
        self.stats["employees"] = StaffProfile.objects.count()
        self.stats["approved_drivers"] = DriverProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED
        ).count()
        return self.stats
