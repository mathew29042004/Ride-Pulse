"""Demo data for the product features, at the network's scale:

* weather for all 33 cities (Open-Meteo, or the seasonal simulation offline);
* big events across the four states over the next two weeks;
* accessibility: ~20% of drivers trained in boarding assistance, a few riders with saved needs;
* teen accounts: parents with teenagers among the bot riders;
* companies on the corporate portal (travel policy, cost centres, travel admins), with
  ``business@ridepulse.dev`` owning one of them.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.drivers.models import DriverProfile, OnboardingStatus
from apps.geo.models import City
from apps.intelligence import context
from apps.intelligence.models import CityEvent, EventKind
from apps.notifications import services as notifications
from apps.realtime import broadcast
from apps.riders import profiles, teens
from apps.riders.models import PaymentProfile, ProfileKind, RiderProfile, TeenLink
from apps.rides.models import RidePreference

User = get_user_model()
BUSINESS_EMAIL = "business@ridepulse.dev"

# (city slug, name, kind, venue, lat, lng, day offset, start hour, hours, crowd)
EVENTS = [
    (
        "chennai",
        "Chennai Super Kings vs Mumbai (exhibition T20)",
        EventKind.CRICKET,
        "M. A. Chidambaram Stadium, Chepauk",
        13.0628,
        80.2793,
        0,
        19,
        4,
        38000,
    ),
    (
        "chennai",
        "A. R. Rahman live",
        EventKind.CONCERT,
        "YMCA Grounds, Nandanam",
        13.0291,
        80.2421,
        3,
        19,
        4,
        25000,
    ),
    (
        "bengaluru",
        "Royal Challengers vs Kolkata (exhibition T20)",
        EventKind.CRICKET,
        "M. Chinnaswamy Stadium",
        12.9788,
        77.5996,
        1,
        19,
        4,
        35000,
    ),
    (
        "bengaluru",
        "Bengaluru Tech Summit",
        EventKind.CONFERENCE,
        "BIEC, Tumakuru Road",
        13.0631,
        77.4752,
        5,
        9,
        9,
        18000,
    ),
    (
        "kochi",
        "Kerala Blasters vs Bengaluru FC",
        EventKind.FOOTBALL,
        "Jawaharlal Nehru Stadium, Kaloor",
        9.9973,
        76.3007,
        2,
        19,
        3,
        32000,
    ),
    (
        "mysuru",
        "Dasara procession (Jamboo Savari)",
        EventKind.FESTIVAL,
        "Mysuru Palace to Bannimantap",
        12.3052,
        76.6552,
        4,
        14,
        6,
        60000,
    ),
    (
        "madurai",
        "Meenakshi temple festival night",
        EventKind.FESTIVAL,
        "Meenakshi Amman Temple",
        9.9195,
        78.1193,
        6,
        18,
        5,
        30000,
    ),
    (
        "coimbatore",
        "Coimbatore Vizha music night",
        EventKind.CONCERT,
        "Codissia Grounds",
        11.0410,
        77.0300,
        2,
        18,
        4,
        15000,
    ),
    (
        "visakhapatnam",
        "India vs Australia ODI (exhibition)",
        EventKind.CRICKET,
        "ACA-VDCA Stadium",
        17.7974,
        83.3528,
        7,
        13,
        8,
        27000,
    ),
    (
        "vijayawada",
        "Dussehra at Kanaka Durga temple",
        EventKind.FESTIVAL,
        "Indrakeeladri",
        16.5160,
        80.6067,
        4,
        6,
        14,
        50000,
    ),
    (
        "thiruvananthapuram",
        "Kerala Literature evening",
        EventKind.CONFERENCE,
        "Kanakakkunnu Palace",
        8.5096,
        76.9563,
        3,
        17,
        4,
        8000,
    ),
    (
        "hubballi-dharwad",
        "Dharwad Utsav",
        EventKind.FESTIVAL,
        "Karnataka College grounds",
        15.4589,
        75.0078,
        8,
        17,
        5,
        12000,
    ),
    (
        "tiruchirappalli",
        "Srirangam temple car festival",
        EventKind.FESTIVAL,
        "Sri Ranganathaswamy Temple",
        10.8628,
        78.6896,
        9,
        7,
        8,
        40000,
    ),
    (
        "mangaluru",
        "Mangaluru Dasara",
        EventKind.FESTIVAL,
        "Kudroli Gokarnanatheshwara Temple",
        12.8724,
        74.8340,
        4,
        18,
        5,
        30000,
    ),
    (
        "kozhikode",
        "Malabar food festival",
        EventKind.FESTIVAL,
        "Kozhikode Beach",
        11.2588,
        75.7684,
        6,
        16,
        6,
        14000,
    ),
    (
        "tirupati",
        "Brahmotsavam Garuda Seva",
        EventKind.FESTIVAL,
        "Tirumala",
        13.6833,
        79.3474,
        5,
        18,
        5,
        45000,
    ),
]
COMPANIES = [
    (
        "chennai",
        "Acme Technologies",
        ["Engineering", "Sales", "Operations"],
        ["MINI", "SEDAN", "AUTO"],
    ),
    ("chennai", "Coromandel Logistics", ["Warehouse", "Finance"], ["MINI", "AUTO", "BIKE"]),
    ("bengaluru", "Nimbus Software", ["Product", "Engineering", "HR"], ["MINI", "SEDAN", "SUV"]),
    ("bengaluru", "Lalbagh Health", ["Clinical", "Admin"], ["MINI", "SEDAN"]),
    ("kochi", "Spice Coast Exports", ["Sales", "Shipping"], ["MINI", "SEDAN", "AUTO"]),
    ("coimbatore", "Kovai Textiles", ["Factory", "Sales"], ["MINI", "AUTO"]),
    ("visakhapatnam", "Bay Shipping Agencies", ["Port ops", "Finance"], ["MINI", "SEDAN"]),
    (
        "thiruvananthapuram",
        "Technopark Analytics",
        ["Engineering", "Support"],
        ["MINI", "SEDAN", "AUTO"],
    ),
    ("madurai", "Temple City Hospitals", ["Clinical", "Admin"], ["MINI", "AUTO"]),
    ("vijayawada", "Krishna Agro Foods", ["Procurement", "Sales"], ["MINI", "SEDAN"]),
    ("mysuru", "Palace Tours & Travels", ["Guides", "Office"], ["MINI", "SUV"]),
    ("mangaluru", "Coastal Bank Ltd", ["Branches", "Treasury"], ["MINI", "SEDAN"]),
]


def seed(*, seed: int = 13, log=print, now: datetime | None = None) -> dict:
    if (
        CityEvent.objects.exists()
        and PaymentProfile.objects.filter(kind=ProfileKind.BUSINESS).count() >= 6
    ):
        return {"product_demo": 0}
    now = now or timezone.now()
    rng = random.Random(seed)
    log("Product features: weather, events, accessibility, teens, companies…")
    stats = {}
    with notifications.muted(), broadcast.muted():
        stats["weather"] = context.refresh_weather(now=now)
        stats["events"] = _events(now)
        stats["assist_trained"] = _assist(rng)
        stats["teens"] = _teens(rng, now)
        stats["companies"] = _companies(rng)
    log(f"  {stats}")
    return stats


def _events(now: datetime) -> int:
    made = 0
    cities = {c.slug: c for c in City.objects.all()}
    today = timezone.localdate(now)
    for slug, name, kind, venue, lat, lng, offset, hour, hours, crowd in EVENTS:
        city = cities.get(slug)
        if city is None or CityEvent.objects.filter(city=city, name=name).exists():
            continue
        start = timezone.make_aware(datetime.combine(today + timedelta(days=offset), time(hour)))
        CityEvent.objects.create(
            city=city,
            name=name,
            kind=kind,
            venue=venue,
            lat=lat,
            lng=lng,
            starts_at=start,
            ends_at=start + timedelta(hours=hours),
            expected_attendance=crowd,
        )
        made += 1
    return made


def _assist(rng: random.Random) -> int:
    drivers = list(
        DriverProfile.objects.filter(onboarding_status=OnboardingStatus.APPROVED).values_list(
            "pk", flat=True
        )
    )
    trained = [pk for pk in drivers if rng.random() < 0.2]
    DriverProfile.objects.filter(pk__in=trained).update(assist_trained=True)
    # A few riders with saved needs (wheelchair users are rarer: they need an accessible car).
    riders = list(
        RiderProfile.objects.filter(user__email__endswith="@example.com").values_list(
            "pk", flat=True
        )[:900]
    )
    for pk in rng.sample(riders, min(len(riders), 18)):
        needs = rng.choice(
            [
                [RidePreference.ASSIST],
                [RidePreference.HEARING],
                [RidePreference.LOW_VISION],
                [RidePreference.WHEELCHAIR],
            ]
        )
        RiderProfile.objects.filter(pk=pk).update(accessibility=needs)
    return len(trained)


def _teens(rng: random.Random, now: datetime) -> int:
    if TeenLink.objects.exists():
        return 0
    pool = list(
        RiderProfile.objects.filter(user__email__endswith="@example.com")
        .exclude(user__phone="")
        .select_related("user")[:900]
    )
    rng.shuffle(pool)
    made = 0
    for guardian, teen in zip(pool[0:50:2], pool[1:50:2], strict=False):
        link = teens.invite(
            guardian, phone=teen.user.phone, monthly_limit=Decimal(rng.choice([1500, 2000, 3000]))
        )
        teens.accept(
            link, user=teen.user, birth_year=timezone.localdate(now).year - rng.randint(13, 17)
        )
        made += 1
    return made


def _companies(rng: random.Random) -> int:
    from apps.simulation.seed import DEMO_PASSWORD

    made = 0
    cities = {c.slug: c for c in City.objects.all()}
    taken = set()
    for n, (slug, name, centres, types) in enumerate(COMPANIES):
        if PaymentProfile.objects.filter(kind=ProfileKind.BUSINESS, name=name).exists():
            continue
        city = cities.get(slug)
        if n == 0:
            owner = _business_owner(DEMO_PASSWORD)
        else:
            owner = (
                RiderProfile.objects.filter(user__email__endswith="@example.com")
                .exclude(pk__in=taken)
                .order_by("?")
                .first()
            )
        taken.add(owner.pk)
        profile = profiles.create_profile(
            owner,
            kind=ProfileKind.BUSINESS,
            name=name,
            gstin=f"33AAACR{rng.randrange(1000, 9999)}Q1Z{rng.randrange(1, 9)}",
        )
        profile.credit_limit = Decimal(rng.choice([50000, 100000, 200000]))
        profile.allowed_ride_types = types
        profile.allowed_from_hour, profile.allowed_to_hour = (6, 23)
        profile.max_fare_per_trip = Decimal(rng.choice([800, 1200, 2000]))
        profile.cost_centers = centres
        profile.save()
        employees = (
            RiderProfile.objects.filter(user__email__endswith="@example.com")
            .exclude(pk__in=taken)
            .exclude(user__phone="")
            .select_related("user")
            .order_by("?")[: rng.randint(8, 25)]
        )
        for i, employee in enumerate(employees):
            taken.add(employee.pk)
            member = profiles.invite(profile, user=owner.user, phone=employee.user.phone)
            profiles.respond(member, user=employee.user, accept=True)
            member.default_cost_center = rng.choice(centres)
            member.is_admin = i == 0
            member.monthly_limit = Decimal(rng.choice([3000, 5000, 8000]))
            member.save()
        made += 1
        _ = city
    return made


def _business_owner(password: str) -> RiderProfile:
    user = User.objects.filter(email=BUSINESS_EMAIL).first()
    if user:
        return user.rider_profile
    from apps.riders.services import register_rider

    return register_rider(
        email=BUSINESS_EMAIL,
        password=password,
        first_name="Divya",
        last_name="Raghavan",
        phone="9840012345",
    )
