"""Demo data for the driver business, at the same scale as the rest of the network:

* fleet owners in every city (two in the big ones), each running 4-12 of its drivers, with the
  city's fleet executive as account manager; ``owner@ridepulse.dev`` is a Chennai owner;
* EV charging stations in every city (more in the metros), more EVs, battery levels;
* realistic odometers, service history, and insurance, permit and fitness dates (a few due);
* PAN cards on file for most drivers (the rest pay 5% TDS);
* live incentive quests per state and in the busiest cities;
* four weeks of weekly statements with TDS.
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from faker import Faker

from apps.accounts.models import Role, StaffProfile
from apps.core.dates import week_start
from apps.drivers.models import (
    DocumentStatus,
    DocumentType,
    DriverDocument,
    DriverProfile,
    FuelType,
    OnboardingStatus,
    Vehicle,
)
from apps.geo.models import City, Zone
from apps.notifications import services as notifications
from apps.pricing.models import RideType
from apps.realtime import broadcast

from . import owners, quests, statements
from .models import ChargingStation, FleetMembership, FleetOwner, ServiceRecord

User = get_user_model()

BIG_CITIES = {
    "chennai",
    "bengaluru",
    "coimbatore",
    "kochi",
    "visakhapatnam",
    "thiruvananthapuram",
    "vijayawada",
    "madurai",
    "mysuru",
}
OPERATORS = [
    ("Tata Power EZ Charge", 60, True, True, "21"),
    ("Statiq", 60, True, True, "19"),
    ("ChargeZone", 120, False, True, "22"),
    ("Jio-bp pulse", 60, True, True, "20"),
    ("Zeon Charging", 60, True, True, "18"),
    ("Ather Grid", 3, True, False, "15"),
    ("Kazam", 7, True, True, "14"),
]
FLEET_NAMES = [
    "{last} Travels",
    "Sri {first} Tours",
    "{city} Cabs",
    "{last} Mobility",
    "{first} Fleet Services",
]
DEMO_OWNER_EMAIL = "owner@ridepulse.dev"


def seed(*, seed: int = 9, log=print, now: datetime | None = None) -> dict:
    if FleetOwner.objects.exists():
        return {"fleet_owners": 0}
    now = now or timezone.now()
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    stats: dict = {}
    log("Setting up the driver business: fleet owners, EVs, vehicle papers, quests…")
    with notifications.muted(), broadcast.muted():
        stats["fleet_owners"] = _owners(rng, fake, now)
        stats["chargers"] = _chargers(rng)
        stats["ev_vehicles"] = _vehicles(rng, now)
        stats["pan_cards"] = _pan_cards(rng)
        stats["quests"] = _quests(rng, now)
        stats["statements"] = sum(
            statements.generate_week(
                week_start(timezone.localdate(now)) - timedelta(days=7 * k), now=now
            )
            for k in (4, 3, 2, 1)
        )
    log(f"  {stats}")
    return stats


def _owners(rng: random.Random, fake: Faker, now: datetime) -> int:
    from apps.simulation.seed import DEMO_PASSWORD

    made = 0
    taken = set(
        FleetMembership.objects.filter(left_at__isnull=True).values_list("driver_id", flat=True)
    )
    for city in City.objects.filter(is_active=True).order_by("name"):
        manager = StaffProfile.objects.filter(user__role=Role.FLEET_EXECUTIVE, city=city).first()
        pool = list(
            DriverProfile.objects.filter(city=city, onboarding_status=OnboardingStatus.APPROVED)
            .exclude(pk__in=taken)
            .exclude(user__email="driver@ridepulse.dev")
            .values_list("pk", flat=True)
        )
        rng.shuffle(pool)
        for n in range(2 if city.slug in BIG_CITIES else 1):
            demo = city.slug == "chennai" and n == 0
            first, last = ("Ravi", "Shankar") if demo else (fake.first_name(), fake.last_name())
            company = rng.choice(FLEET_NAMES).format(first=first, last=last, city=city.name)
            email = (
                DEMO_OWNER_EMAIL if demo else f"fleet.{city.slug}.{n + 1}@partners.ridepulse.dev"
            )
            if User.objects.filter(email=email).exists():
                continue
            owner = owners.create_owner(
                email=email,
                first_name=first,
                last_name=last,
                phone=f"97{rng.randrange(10**7, 10**8)}",
                company_name=company,
                city=city,
                gstin=_gstin(rng),
                share_percent=Decimal(rng.choice(["15", "18", "20", "22", "25"])),
                account_manager=manager,
                password=DEMO_PASSWORD,
            )
            size = rng.randint(4, 12 if city.slug in BIG_CITIES else 6)
            for driver_id in pool[:size]:
                owners.add_driver(
                    owner,
                    DriverProfile.objects.get(pk=driver_id),
                    now=now - timedelta(days=rng.randint(30, 400)),
                )
                taken.add(driver_id)
            pool = pool[size:]
            made += 1
    return made


def _gstin(rng: random.Random) -> str:
    state, digits, check = rng.randrange(10, 37), rng.randrange(1000, 9999), rng.randrange(1, 9)
    return f"{state}ABCDE{digits}F1Z{check}"


def _chargers(rng: random.Random) -> int:
    made = 0
    for city in City.objects.filter(is_active=True):
        zones = list(Zone.objects.filter(city=city))
        count = 8 if city.slug in {"chennai", "bengaluru"} else 5 if city.slug in BIG_CITIES else 3
        for zone in rng.sample(zones, min(count, len(zones))):
            operator, kw, two, four, price = rng.choice(OPERATORS)
            ChargingStation.objects.create(
                city=city,
                name=f"{operator} · {zone.name}",
                operator=operator,
                lat=zone.center_lat + rng.uniform(-0.006, 0.006),
                lng=zone.center_lng + rng.uniform(-0.006, 0.006),
                power_kw=kw,
                connectors=rng.choice([2, 4, 6]),
                two_wheeler=two,
                four_wheeler=four,
                price_per_kwh=Decimal(price),
            )
            made += 1
    return made


def _vehicles(rng: random.Random, now: datetime) -> int:
    from django.db.models import Sum

    from apps.rides.models import Trip, TripStatus

    today = timezone.localdate(now)
    interval = {"BIKE": 3000, "AUTO": 5000}
    driven = dict(
        Trip.objects.filter(status=TripStatus.COMPLETED, vehicle__isnull=False)
        .values_list("vehicle_id")
        .annotate(km=Sum("actual_distance_km"))
        .values_list("vehicle_id", "km")
    )
    for vehicle in Vehicle.objects.filter(is_active=True).select_related("ride_type"):
        code = vehicle.ride_type.code
        age = max(1, today.year - vehicle.year)
        base = int(age * rng.uniform(9_000, 22_000) * (0.6 if code == "BIKE" else 1))
        now_km = base + int(driven.get(vehicle.pk) or 0)
        every = interval.get(code, 10_000)
        # Most were serviced recently; about 1 in 10 is due soon and 1 in 25 overdue.
        since = int(
            every
            * rng.choices([rng.uniform(0.05, 0.9), rng.uniform(0.95, 0.99), 1.03], [86, 10, 4])[0]
        )
        fields = {
            "odometer_base_km": base,
            "last_service_km": max(0, now_km - since),
            "insurance_expires_on": today
            + timedelta(days=rng.choice([12, 25, *range(45, 700, 15)])),
            "permit_expires_on": today + timedelta(days=rng.choice([-5, 20, *range(60, 1500, 30)])),
            "fitness_expires_on": today + timedelta(days=rng.choice([18, *range(90, 900, 30)])),
        }
        # Lift EVs towards ~15% of the fleet (autos and bikes first, like real Indian fleets).
        if vehicle.fuel_type != FuelType.EV and rng.random() < {"AUTO": 0.12, "BIKE": 0.1}.get(
            code, 0.05
        ):
            fields["fuel_type"] = FuelType.EV
        if fields.get("fuel_type", vehicle.fuel_type) == FuelType.EV:
            fields["battery_percent"] = rng.randint(25, 100)
            fields["battery_updated_at"] = now
        if code in ("MINI", "SUV") and rng.random() < 0.04:
            fields["wheelchair_accessible"] = True
        Vehicle.objects.filter(pk=vehicle.pk).update(**fields)
        if since < every and rng.random() < 0.7:
            ServiceRecord.objects.create(
                vehicle=vehicle,
                odometer_km=max(0, now_km - since),
                serviced_on=today - timedelta(days=rng.randint(10, 150)),
                workshop=rng.choice(
                    [
                        "Authorised service centre",
                        "Bosch Car Service",
                        "Local garage",
                        "Fleet workshop",
                    ]
                ),
            )
    return Vehicle.objects.filter(fuel_type=FuelType.EV, is_active=True).count()


def _pan_cards(rng: random.Random) -> int:
    have = set(
        DriverDocument.objects.filter(doc_type=DocumentType.PAN).values_list("driver_id", flat=True)
    )
    admin = User.objects.filter(role=Role.ADMIN).first()
    rows = [
        DriverDocument(
            driver_id=pk,
            doc_type=DocumentType.PAN,
            number_last4=f"{rng.randrange(1000, 9999)}",
            status=DocumentStatus.APPROVED,
            reviewed_by=admin,
            reviewed_at=timezone.now(),
        )
        for pk in DriverProfile.objects.filter(onboarding_status=OnboardingStatus.APPROVED)
        .exclude(pk__in=have)
        .values_list("pk", flat=True)
        if rng.random() < 0.72
    ]
    DriverDocument.objects.bulk_create(rows)
    return len(rows)


def _quests(rng: random.Random, now: datetime) -> int:
    admin = User.objects.filter(role=Role.ADMIN).first()
    today = timezone.localdate(now)
    monday = week_start(today)
    friday = timezone.make_aware(datetime.combine(monday + timedelta(days=4), datetime.min.time()))
    if friday <= now:
        friday = now
    sunday_night = timezone.make_aware(
        datetime.combine(monday + timedelta(days=6), datetime.max.time().replace(microsecond=0))
    )
    if sunday_night <= now:
        sunday_night = now + timedelta(days=3)
    week_end = now + timedelta(days=7)
    made = 0
    for state in ("Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh"):
        quests.create_quest(
            user=admin,
            name=f"Weekend warrior · {state}",
            state=state,
            starts_at=friday,
            ends_at=sunday_night,
            tiers=[[8, 150], [15, 350], [25, 700]],
            budget=Decimal("150000"),
            now=now,
        )
        made += 1
    for city in City.objects.filter(slug__in=BIG_CITIES):
        quests.create_quest(
            user=admin,
            name=f"Peak hour hero · {city.name}",
            city=city,
            starts_at=now - timedelta(hours=2),
            ends_at=week_end,
            tiers=[[5, 100], [12, 300]],
            peak_hours_only=True,
            budget=Decimal("40000"),
            now=now,
        )
        made += 1
    bikes = RideType.objects.filter(code__in=["BIKE", "PARCEL"])
    for slug in ("chennai", "bengaluru"):
        quests.create_quest(
            user=admin,
            name=f"Bike sprint · {City.objects.get(slug=slug).name}",
            city=City.objects.get(slug=slug),
            ride_types=bikes,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=3),
            tiers=[[6, 80], [15, 250]],
            min_rating=Decimal("4.5"),
            budget=Decimal("25000"),
            now=now,
        )
        made += 1
    return made
