"""Demo data: a believable few weeks of Ride Pulse history.

Nothing is inserted behind the services' backs. Every trip is booked, dispatched, accepted,
driven, paid for and rated through the same service functions the API uses, just with the clock
set to a time in the past. So the ledger balances, ratings and safety scores add up, and the
audit trail is real.
"""

import math
import random
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from faker import Faker

from apps.accounts.models import Role
from apps.core.exceptions import DomainError
from apps.drivers import services as drivers_svc
from apps.drivers.models import REQUIRED_DOCUMENTS, Availability, DocumentType, DriverProfile
from apps.geo.distance import haversine_km, offset
from apps.geo.models import City
from apps.notifications import services as notifications
from apps.notifications.models import Level
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.pricing.models import PromoCode, RideType, SurgeSnapshot
from apps.realtime import broadcast
from apps.riders.models import PlaceLabel, RiderProfile, SavedPlace
from apps.riders.services import register_rider
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import OfferStatus, Trip, TripStatus
from apps.support import services as support
from apps.support.models import SafetyIncident, SupportTicket, TicketCategory, TicketMessage

from .fleet_data import (
    CITY_WEIGHTS,
    COLORS,
    HOURLY_DEMAND,
    LOW_TAGS,
    PAYMENT_WEIGHTS,
    RIDE_TYPE_WEIGHTS,
    RIDER_TAGS,
    RTO_CODES,
    VEHICLES,
)

DEMO_PASSWORD = "RidePulse@2026"
DRIVERS_PER_CITY = {"chennai": 40, "bengaluru": 36, "coimbatore": 18}

STAFF = [
    ("admin@ridepulse.dev", "Asha", "Menon", Role.ADMIN),
    ("ops@ridepulse.dev", "Meera", "Krishnan", Role.OPS_MANAGER),
    ("ops2@ridepulse.dev", "Rohan", "Iyer", Role.OPS_MANAGER),
    ("support@ridepulse.dev", "Arjun", "Nair", Role.SUPPORT_AGENT),
    ("support2@ridepulse.dev", "Divya", "Shankar", Role.SUPPORT_AGENT),
]


def _weighted(rng: random.Random, weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


class Seeder:
    def __init__(
        self,
        *,
        days: int = 21,
        trips_per_day: int = 50,
        riders: int = 150,
        seed: int = 42,
        log: Callable[[str], None] = print,
    ):
        self.days = days
        self.trips_per_day = trips_per_day
        self.rider_count = riders
        self.rng = random.Random(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.log = log
        self.now = timezone.now()
        self.stats: dict[str, int] = {}
        self.busy_until: dict[int, datetime] = {}
        self.profile: dict[int, dict] = {}
        self.used_emails: set[str] = set()
        self.used_plates: set[str] = set()
        self.used_phones: set[str] = set()

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    # --- People ----------------------------------------------------------------------------

    def _email(self, first: str, last: str, domain: str) -> str:
        base = re.sub(r"[^a-z0-9.]", "", f"{first}.{last}".lower()) or "user"
        email, n = f"{base}@{domain}", 1
        while email in self.used_emails:
            n += 1
            email = f"{base}{n}@{domain}"
        self.used_emails.add(email)
        return email

    def _phone(self) -> str:
        """A random mobile number no account uses yet (phone numbers are unique logins)."""
        while True:
            phone = f"{self.rng.choice('6789')}{self.rng.randrange(10**8, 10**9)}"
            if phone not in self.used_phones:
                self.used_phones.add(phone)
                return phone

    def create_staff(self) -> None:
        User = get_user_model()
        staff = {}
        for email, first, last, role in STAFF:
            if role == Role.ADMIN:
                staff[email] = User.objects.create_superuser(
                    email, DEMO_PASSWORD, first_name=first, last_name=last
                )
            else:
                staff[email] = User.objects.create_user(
                    email, DEMO_PASSWORD, first_name=first, last_name=last, role=role
                )
        self.admin = staff["admin@ridepulse.dev"]
        self.ops_manager = staff["ops@ridepulse.dev"]
        self.support_agent = staff["support@ridepulse.dev"]

    def create_riders(self) -> None:
        demo = register_rider(
            email="rider@ridepulse.dev",
            password=DEMO_PASSWORD,
            first_name="Priya",
            last_name="Raman",
            phone="9876543210",
        )
        demo.emergency_contact_name = "Lakshmi Raman"
        demo.emergency_contact_phone = "9876500011"
        demo.save()
        SavedPlace.objects.create(
            rider=demo,
            label=PlaceLabel.HOME,
            name="Anna Nagar",
            address="2nd Avenue, Anna Nagar, Chennai",
            lat=13.0878,
            lng=80.2095,
        )
        SavedPlace.objects.create(
            rider=demo,
            label=PlaceLabel.WORK,
            name="Tidel Park",
            address="Taramani, Chennai",
            lat=12.9893,
            lng=80.2484,
        )
        payments.top_up(demo.user, Decimal(1500), method="UPI", payer_reference="priya@okaxis")
        self.demo_rider = demo
        self.riders = [demo]
        for _ in range(self.rider_count):
            first, last = self.fake.first_name(), self.fake.last_name()
            rider = register_rider(
                email=self._email(first, last, "example.com"),
                password=None,
                first_name=first,
                last_name=last,
                phone=self._phone(),
            )
            if self.rng.random() < 0.4:
                payments.top_up(
                    rider.user,
                    Decimal(self.rng.choice([200, 500, 1000, 2000])),
                    method="UPI",
                    payer_reference="seed@upi",
                )
            self.riders.append(rider)
        self.count("riders", len(self.riders))

    def _plate(self, city_slug: str) -> str:
        while True:
            letters = "".join(self.rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
            plate = (
                f"{self.rng.choice(RTO_CODES[city_slug])}{letters}{self.rng.randrange(1000, 9999)}"
            )
            if plate not in self.used_plates:
                self.used_plates.add(plate)
                return plate

    def _add_driver(
        self,
        city: City,
        *,
        email=None,
        password=None,
        first=None,
        last=None,
        ride_type=None,
        vehicle=None,
        documents="approved",
    ) -> DriverProfile:
        woman = False
        if first is None:
            woman = self.rng.random() >= 0.9  # about one driver in ten is a woman
            first = self.fake.first_name_female() if woman else self.fake.first_name_male()
        last = last or self.fake.last_name()
        driver = drivers_svc.register_driver(
            email=email or self._email(first, last, "drivers.example.com"),
            password=password,
            first_name=first,
            last_name=last,
            phone=self._phone(),
            city=city,
            license_number=(
                f"{RTO_CODES[city.slug][0]}{self.rng.randrange(2008, 2022)}"
                f"{self.rng.randrange(10**6, 10**7)}"
            ),
            license_expiry=date(self.rng.randrange(2029, 2036), self.rng.randrange(1, 13), 1),
            gender="FEMALE" if woman else "MALE",
        )
        code = ride_type or _weighted(self.rng, RIDE_TYPE_WEIGHTS)
        make, model, seats = vehicle or self.rng.choice(VEHICLES[code])
        vehicle_row = drivers_svc.register_vehicle(
            driver,
            ride_type=self.ride_types[code],
            make=make,
            model=model,
            registration_number=self._plate(city.slug) if not email else "TN09AB1234",
            year=self.rng.randrange(2017, 2026),
            color=self.rng.choice(COLORS),
            seats=seats,
        )
        fuel = {"AUTO": "CNG", "SUV": "DIESEL"}.get(code, "PETROL")
        if code in ("BIKE", "MINI") and self.rng.random() < 0.15:
            fuel = "EV"
        type(vehicle_row).objects.filter(pk=vehicle_row.pk).update(fuel_type=fuel)
        submit = (
            list(REQUIRED_DOCUMENTS) if documents != "partial" else [DocumentType.DRIVING_LICENSE]
        )
        for doc_type in submit:
            expires = self.now.date() + timedelta(days=self.rng.randrange(300, 1500))
            document = drivers_svc.submit_document(
                driver,
                doc_type=doc_type,
                number_last4=f"{self.rng.randrange(1000, 9999)}",
                expires_on=expires,
            )
            if documents == "approved":
                drivers_svc.review_document(document, approve=True, reviewer=self.ops_manager)
        driver.refresh_from_db()
        self.profile[driver.pk] = {
            "quality": min(5.0, max(3.2, self.rng.gauss(4.65, 0.3))),
            "risk": self.rng.random() ** 2,  # most drivers drive safely, a few don't
            "activity": self.rng.uniform(0.4, 1.6),
            "ride_type": code,
        }
        return driver

    def create_drivers(self) -> None:
        self.city_drivers: dict[str, list[DriverProfile]] = {slug: [] for slug in self.cities}
        chennai = self.cities["chennai"]
        self.demo_driver = self._add_driver(
            chennai,
            email="driver@ridepulse.dev",
            password=DEMO_PASSWORD,
            first="Karthik",
            last="Rajan",
            ride_type="MINI",
            vehicle=("Maruti Suzuki", "Swift", 4),
        )
        self.profile[self.demo_driver.pk].update(quality=4.85, risk=0.05, activity=1.4)
        self.city_drivers["chennai"].append(self.demo_driver)
        for slug, count in DRIVERS_PER_CITY.items():
            city = self.cities[slug]
            for i in range(count):
                documents = (
                    "approved" if i < count - 5 else ("submitted" if i < count - 2 else "partial")
                )
                driver = self._add_driver(city, documents=documents)
                if documents == "approved":
                    self.city_drivers[slug].append(driver)
        self.count("drivers", DriverProfile.objects.count())

    def create_promos(self) -> None:
        start = self.now - timedelta(days=self.days + 1)
        end = self.now + timedelta(days=60)
        PromoCode.objects.create(
            code="WELCOME50",
            description="50% off your first ride (up to ₹75)",
            discount_type="PERCENT",
            value=50,
            max_discount=75,
            valid_from=start,
            valid_until=end,
            first_ride_only=True,
        )
        PromoCode.objects.create(
            code="RIDEPULSE20",
            description="20% off, up to ₹60, three times",
            discount_type="PERCENT",
            value=20,
            max_discount=60,
            valid_from=start,
            valid_until=end,
            max_per_rider=3,
        )
        PromoCode.objects.create(
            code="CHENNAI100",
            description="₹100 off rides above ₹300 in Chennai",
            discount_type="FLAT",
            value=100,
            min_fare=300,
            valid_from=start,
            valid_until=end,
            city=self.cities["chennai"],
            max_redemptions=500,
        )
        PromoCode.objects.create(
            code="MONSOON25",
            description="25% off during the monsoon (up to ₹80)",
            discount_type="PERCENT",
            value=25,
            max_discount=80,
            valid_from=start,
            valid_until=end,
            max_per_rider=2,
        )

    def surge_history(self) -> None:
        """Synthetic 15-minute surge snapshots, following the daily demand curve."""
        rows = []
        first = timezone.localtime(self.now - timedelta(days=self.days)).replace(
            minute=0, second=0, microsecond=0
        )
        slots = int((self.now - first).total_seconds() // 900)
        for city in self.cities.values():
            for zone in city.zones.all():
                for s in range(slots):
                    at = first + timedelta(minutes=15 * s)
                    pressure = (
                        HOURLY_DEMAND[at.hour] * zone.demand_weight * self.rng.uniform(0.75, 1.3)
                    )
                    multiplier = 1 + max(0.0, pressure - 1.35) * 1.4
                    multiplier = round(min(multiplier, 2.5), 1)
                    if multiplier > 1:
                        demand = int(8 * pressure)
                        rows.append(
                            SurgeSnapshot(
                                zone=zone,
                                multiplier=Decimal(str(multiplier)),
                                demand=demand,
                                supply=max(1, int(demand / multiplier)),
                                computed_at=at,
                            )
                        )
        SurgeSnapshot.objects.bulk_create(rows, batch_size=2000)
        self.count("surge_snapshots", len(rows))

    # --- Trips -----------------------------------------------------------------------------

    def _point_in(self, center_lat, center_lng, radius_km):
        angle = self.rng.uniform(0, 2 * math.pi)
        distance = radius_km * math.sqrt(self.rng.random())
        return offset(
            center_lat, center_lng, distance * math.cos(angle), distance * math.sin(angle)
        )

    def _endpoints(self, city: City):
        zones = list(city.zones.all())
        landmarks = list(city.landmarks.all())
        pickup_zone = self.rng.choices(zones, weights=[z.demand_weight for z in zones])[0]
        pickup = self._point_in(
            pickup_zone.center_lat, pickup_zone.center_lng, pickup_zone.radius_km * 0.8
        )
        for _ in range(8):
            if landmarks and self.rng.random() < 0.35:
                place = self.rng.choice(landmarks)
                dropoff, name = (place.lat, place.lng), place.name
            else:
                zone = self.rng.choices(zones, weights=[z.demand_weight for z in zones])[0]
                dropoff, name = (
                    self._point_in(zone.center_lat, zone.center_lng, zone.radius_km * 0.8),
                    zone.name,
                )
            distance = haversine_km(*pickup, *dropoff)
            if 1.5 <= distance <= 28 and city.contains(*dropoff):
                return pickup, pickup_zone.name, dropoff, name
        return None

    def _online_near(
        self, driver: DriverProfile, pickup, at: datetime, km_range=(0.4, 3.0)
    ) -> None:
        if payments.wallet_balance(driver.user) < -300:
            payments.pay_dues(driver.user, method="UPI", payer_reference="seed@upi")
        angle = self.rng.uniform(0, 2 * math.pi)
        distance = self.rng.uniform(*km_range)
        lat, lng = offset(*pickup, distance * math.cos(angle), distance * math.sin(angle))
        drivers_svc.go_online(driver, lat=lat, lng=lng, now=at)

    def _offline(self, driver: DriverProfile, at: datetime) -> None:
        driver.refresh_from_db(fields=["availability"])
        if driver.availability == Availability.ONLINE:
            drivers_svc.go_offline(driver, now=at)
        self.busy_until[driver.pk] = at

    def _active_types(self, city) -> set[str]:
        cache = self.__dict__.setdefault("_types_by_city", {})
        if city.pk not in cache:
            from apps.pricing.models import FareRule

            cache[city.pk] = set(
                FareRule.objects.filter(city=city, is_active=True).values_list(
                    "ride_type__code", flat=True
                )
            )
        return cache[city.pk]

    def _available(self, slug: str, ride_type: str, at: datetime) -> list[DriverProfile]:
        return [
            d
            for d in self.city_drivers[slug]
            if self.profile[d.pk]["ride_type"] == ride_type and self.busy_until.get(d.pk, at) <= at
        ]

    def _telemetry(self, driver: DriverProfile, distance: float, night: bool) -> dict:
        risk = self.profile[driver.pk]["risk"]
        return {
            "harsh_brakes": int(self.rng.random() < 0.3 + risk)
            + int(distance / 10 * risk * self.rng.uniform(0, 4)),
            "harsh_accelerations": int(distance / 10 * risk * self.rng.uniform(0, 3)),
            "speeding_seconds": int(risk * self.rng.uniform(0, 240)),
            "night_distance_km": round(distance, 2) if night else 0,
        }

    def _stars(self, driver: DriverProfile) -> int:
        quality = self.profile[driver.pk]["quality"]
        return max(1, min(5, round(self.rng.gauss(quality, 0.55))))

    def one_trip(self, at: datetime, slug: str) -> Trip | None:
        rng, city = self.rng, self.cities[slug]
        endpoints = self._endpoints(city)
        if endpoints is None:
            return None
        pickup, pickup_name, dropoff, dropoff_name = endpoints
        ride_type = _weighted(rng, RIDE_TYPE_WEIGHTS)
        if ride_type not in self._active_types(city):  # paused here: no driver can serve it
            return None
        if not self.ride_types[ride_type].is_open(at):  # e.g. bikes run 5 am to 11 pm
            return None
        rider = (
            self.demo_rider
            if (slug == "chennai" and rng.random() < 0.06)
            else rng.choice(self.riders)
        )
        if rider.is_blocked:
            return None
        if payments.wallet_balance(rider.user) < 0:
            payments.pay_dues(rider.user, method="UPI", payer_reference="seed@upi")
        method = _weighted(rng, PAYMENT_WEIGHTS)
        if method == "WALLET" and payments.wallet_balance(rider.user) < 600:
            method = "UPI"
        promo = (
            rng.choice(["RIDEPULSE20", "WELCOME50", "MONSOON25", "CHENNAI100"])
            if rng.random() < 0.08
            else ""
        )
        outcome = rng.random()
        available = self._available(slug, ride_type, at)
        no_driver = outcome < 0.045 or not available

        online = []
        if not no_driver:
            weights = [self.profile[d.pk]["activity"] for d in available]
            driver = rng.choices(available, weights=weights)[0]
            self._online_near(driver, pickup, at - timedelta(seconds=60))
            online.append(driver)
            if outcome < 0.08 and len(available) > 1:  # the first driver declines, a second accepts
                second = rng.choice([d for d in available if d.pk != driver.pk])
                self._online_near(second, pickup, at - timedelta(seconds=50), km_range=(2.5, 4.0))
                online.append(second)

        def request(code, pay):
            return rides.request_trip(
                rider=rider,
                ride_type=self.ride_types[ride_type],
                pickup=pickup,
                dropoff=dropoff,
                pickup_address=pickup_name,
                dropoff_address=dropoff_name,
                payment_method=pay,
                promo_code=code,
                now=at,
            )

        try:
            trip = request(promo, method)
        except DomainError:  # promo not eligible or wallet too low: book like a regular rider
            trip = request("", "UPI")

        if no_driver:
            dispatch.sweep(now=trip.dispatch_deadline + timedelta(seconds=1))
            self.count("no_driver")
            return trip

        offer = trip.offers.filter(status=OfferStatus.PENDING).select_related("driver").first()
        if offer is None:
            rides.cancel_trip(
                trip, user=rider.user, reason="Took too long", now=at + timedelta(minutes=2)
            )
            for d in online:
                self._offline(d, at + timedelta(minutes=3))
            return trip

        if 0.08 <= outcome < 0.12:  # rider changes plans before anyone accepts
            rides.cancel_trip(
                trip,
                user=rider.user,
                reason="Changed my plans",
                now=at + timedelta(seconds=rng.randrange(20, 90)),
            )
            for d in online:
                self._offline(d, at + timedelta(minutes=rng.randrange(3, 15)))
            self.count("cancelled")
            return trip

        t = at + timedelta(seconds=rng.randrange(5, 17))
        if outcome < 0.08 and len(online) > 1:
            dispatch.decline_offer(offer, driver=offer.driver, now=t)
            offer = trip.offers.filter(status=OfferStatus.PENDING).select_related("driver").first()
            t += timedelta(seconds=rng.randrange(5, 16))
            if offer is None:
                return trip
        trip = dispatch.accept_offer(offer, driver=offer.driver, now=t)
        driver = trip.driver
        for d in online:
            if d.pk != driver.pk:
                self._offline(d, t + timedelta(minutes=rng.randrange(2, 12)))

        if 0.12 <= outcome < 0.15:  # rider cancels late and pays the cancellation fee
            cancelled_at = t + timedelta(seconds=rng.randrange(150, 360))
            rides.cancel_trip(
                trip, user=rider.user, reason="Driver was taking too long", now=cancelled_at
            )
            self._offline(driver, cancelled_at + timedelta(minutes=rng.randrange(1, 10)))
            self.count("cancelled_with_fee")
            return trip

        t_arrive = t + timedelta(minutes=float(offer.eta_minutes) * rng.uniform(0.8, 1.4))
        near_pickup = offset(*pickup, rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05))
        drivers_svc.update_location(
            driver, lat=near_pickup[0], lng=near_pickup[1], now=t_arrive - timedelta(seconds=5)
        )
        trip = rides.mark_arrived(trip, driver=driver, now=t_arrive)
        t_start = t_arrive + timedelta(minutes=rng.uniform(0.5, 4.5))
        trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=t_start)

        deviation = rng.random() < 0.02
        distance = float(trip.estimated_distance_km) * (
            rng.uniform(1.55, 1.8) if deviation else rng.uniform(0.95, 1.12)
        )
        # Real traffic (city, time, rain, centre, vehicle), which the app's estimate can't see.
        from .traffic import true_minutes

        duration = true_minutes(trip, t_start, rng) * (rng.uniform(1.35, 1.6) if deviation else 1)
        t_end = t_start + timedelta(minutes=duration)
        for i in range(1, 6):
            f = i / 6
            lat = pickup[0] + (dropoff[0] - pickup[0]) * f + rng.uniform(-0.003, 0.003)
            lng = pickup[1] + (dropoff[1] - pickup[1]) * f + rng.uniform(-0.003, 0.003)
            drivers_svc.update_location(
                driver, lat=lat, lng=lng, now=t_start + (t_end - t_start) * f
            )
        drivers_svc.update_location(
            driver, lat=dropoff[0], lng=dropoff[1], now=t_end - timedelta(seconds=3)
        )
        local_hour = timezone.localtime(t_start).hour
        trip = rides.complete_trip(
            trip,
            driver=driver,
            now=t_end,
            actual_distance_km=round(distance, 2),
            telemetry=self._telemetry(driver, distance, night=local_hour >= 23 or local_hour < 5),
            payer_reference="fail@upi" if rng.random() < 0.02 else "seed@upi",
        )
        self.count("completed")

        if rng.random() < 0.85:
            stars = self._stars(driver)
            tags = (
                rng.sample(RIDER_TAGS, rng.randrange(0, 3))
                if stars >= 4
                else rng.sample(LOW_TAGS, 1)
            )
            rides.rate_trip(
                trip,
                user=rider.user,
                stars=stars,
                tags=tags,
                now=t_end + timedelta(minutes=rng.randrange(1, 40)),
            )
        if rng.random() < 0.7:
            rides.rate_trip(
                trip,
                user=driver.user,
                stars=rng.choices([5, 4, 3], weights=[80, 16, 4])[0],
                now=t_end + timedelta(minutes=2),
            )
        if rng.random() < 0.07:
            rides.tip_driver(
                trip,
                user=rider.user,
                amount=Decimal(rng.choice([20, 30, 50, 100])),
                method="UPI",
                payer_reference="seed@upi",
                now=t_end + timedelta(minutes=5),
            )
            self.count("tips")
        if rng.random() < 0.03:
            self._ticket(trip, rider, t_end + timedelta(hours=rng.uniform(0.2, 20)))
        self._offline(driver, t_end + timedelta(minutes=rng.randrange(1, 25)))
        return trip

    def _ticket(self, trip: Trip, rider: RiderProfile, at: datetime) -> None:
        category, subject, text = self.rng.choice(
            [
                (
                    TicketCategory.FARE_DISPUTE,
                    "I was charged more than the estimate",
                    "The route seemed longer than needed and the fare went up.",
                ),
                (
                    TicketCategory.LOST_ITEM,
                    "Left my bag in the car",
                    "I left a black backpack on the back seat. Can you help me reach the driver?",
                ),
                (
                    TicketCategory.DRIVER_BEHAVIOUR,
                    "Driver was rude",
                    "The driver was on the phone the whole trip and argued about the route.",
                ),
                (
                    TicketCategory.PAYMENT,
                    "Charged twice for one ride",
                    "I see two UPI debits for the same trip.",
                ),
            ]
        )
        ticket = support.open_ticket(
            user=rider.user, category=category, subject=subject, description=text, trip=trip, now=at
        )
        SupportTicket.objects.filter(pk=ticket.pk).update(created_at=at)
        if at < self.now - timedelta(days=1) and self.rng.random() < 0.75:
            agent = ticket.assigned_to or self.support_agent
            message = support.reply(
                ticket,
                author=agent,
                body="Thanks for reaching out. We're looking into this trip now.",
            )
            refund = (
                min(Decimal(60), trip.fare_total or 0)
                if category in (TicketCategory.FARE_DISPUTE, TicketCategory.PAYMENT)
                else Decimal(0)
            )
            support.resolve(
                ticket,
                actor=self.admin,
                resolution="We've reviewed the trip and sorted it out. Sorry for the trouble!",
                refund_amount=refund,
            )
            self._backdate_ticket(ticket, message, at)
        self.count("tickets")

    def _backdate_ticket(self, ticket, message, at: datetime) -> None:
        """History happened in the past: first reply within minutes, resolved mostly in SLA."""
        replied = at + timedelta(minutes=self.rng.triangular(3, 180, 20))
        if message is not None:
            TicketMessage.objects.filter(pk=message.pk).update(created_at=replied)
        late = self.rng.random() < 0.15
        resolved = (
            ticket.sla_due_at + timedelta(hours=self.rng.uniform(1, 12))
            if late
            else replied + (ticket.sla_due_at - replied) * self.rng.uniform(0.1, 0.9)
        )
        SupportTicket.objects.filter(pk=ticket.pk).update(resolved_at=max(resolved, replied))

    def _sos(self, trip: Trip, *, resolve: bool) -> None:
        raised_at = trip.completed_at - timedelta(minutes=4)
        incident = support.raise_sos(
            trip=trip,
            user=trip.rider.user,
            note="The driver is driving very fast and not stopping.",
            now=trip.completed_at + timedelta(minutes=3),
        )
        if resolve:
            support.acknowledge_incident(incident, actor=self.support_agent)
            support.resolve_incident(
                incident,
                actor=self.support_agent,
                note="Called the rider and the driver. The rider reached home safely; "
                "the driver was warned.",
            )
        # Last, because resolving saves the whole row (including created_at).
        SafetyIncident.objects.filter(pk=incident.pk).update(created_at=raised_at)
        SupportTicket.objects.filter(pk=incident.ticket_id).update(created_at=raised_at)
        self.count("sos")

    def history(self) -> None:
        events = []
        today = timezone.localdate(self.now)
        cutoff = self.now - timedelta(minutes=90)
        for d in range(self.days, -1, -1):
            day = today - timedelta(days=d)
            factor = 1.15 if day.weekday() >= 5 else 1.0
            n = int(self.trips_per_day * factor * self.rng.uniform(0.85, 1.15))
            for _ in range(n):
                hour = self.rng.choices(range(24), weights=HOURLY_DEMAND)[0]
                at = timezone.make_aware(
                    datetime.combine(
                        day, time(hour, self.rng.randrange(60), self.rng.randrange(60))
                    )
                )
                if at < cutoff:
                    events.append((at, _weighted(self.rng, CITY_WEIGHTS)))
        events.sort()
        mondays = sorted(
            timezone.make_aware(datetime.combine(today - timedelta(days=d), time(4, 0)))
            for d in range(self.days)
            if (today - timedelta(days=d)).weekday() == 0
        )
        self.log(f"Simulating {len(events)} trips over {self.days} days…")
        completed: list[Trip] = []
        for i, (at, slug) in enumerate(events, 1):
            while mondays and mondays[0] <= at:
                self._payouts(mondays.pop(0))
            trip = self.one_trip(at, slug)
            if trip is not None and trip.status == TripStatus.COMPLETED:
                completed.append(trip)
            if i % 100 == 0:
                self.log(f"  {i}/{len(events)} trips")
        old = [t for t in completed if t.completed_at < self.now - timedelta(days=3)]
        for trip in self.rng.sample(old, min(2, len(old))):
            self._sos(trip, resolve=True)
        if completed:
            self._sos(completed[-1], resolve=False)

    def _payouts(self, at: datetime) -> None:
        for payout in payments.create_weekly_payouts(now=at):
            if self.rng.random() < 0.97:
                payments.mark_payout_paid(
                    payout, bank_reference=f"UTR{self.rng.randrange(10**11, 10**12)}"
                )
            else:
                payments.mark_payout_failed(payout, reason="Bank account details are invalid.")
            self.count("payouts")

    # --- Finishing touches -----------------------------------------------------------------

    def finish(self) -> None:
        for driver in DriverProfile.objects.exclude(availability=Availability.OFFLINE):
            drivers_svc.go_offline(driver, now=self.now)
        # Spread sign-up dates over the past year so "joined" columns look real.
        for model in (RiderProfile, DriverProfile):
            for pk in model.objects.values_list("pk", flat=True):
                model.objects.filter(pk=pk).update(
                    created_at=self.now - timedelta(days=self.days + self.rng.randrange(1, 365))
                )
        for payment in Payment.objects.filter(trip__isnull=False).select_related("trip"):
            when = payment.trip.completed_at or payment.trip.requested_at
            Payment.objects.filter(pk=payment.pk).update(created_at=when)
        risky = (
            DriverProfile.objects.filter(onboarding_status="APPROVED", city__slug="bengaluru")
            .exclude(user__email="driver@ridepulse.dev")
            .order_by("rating")
            .first()
        )
        if risky:
            drivers_svc.suspend_driver(
                risky,
                reason="Three safety complaints in two weeks; under investigation.",
                actor=self.ops_manager,
            )
        RiderProfile.objects.filter(pk=self.riders[-1].pk).update(
            is_blocked=True, blocked_reason="Repeated payment chargebacks."
        )

    def welcome(self) -> None:
        notifications.notify(
            self.demo_rider.user,
            "Welcome back to Ride Pulse",
            "Use code RIDEPULSE20 for 20% off your next three rides.",
            level=Level.SUCCESS,
            link="/ride/book",
        )
        notifications.notify(
            self.demo_driver.user,
            "Peak hours are coming",
            "Demand rises from 5 pm. Head towards T. Nagar or OMR to catch surge fares.",
            level=Level.INFO,
            link="/drive",
        )
        for user in (self.ops_manager, self.admin):
            notifications.notify(
                user,
                "Weekly payouts completed",
                "Driver payouts for last week were sent to banks.",
                level=Level.SUCCESS,
                link="/ops/finance",
            )

    def run(self) -> dict:
        self.cities = {c.slug: c for c in City.objects.filter(is_active=True)}
        self.ride_types = {rt.code: rt for rt in RideType.objects.all()}
        with notifications.muted(), broadcast.muted():
            self.log("Creating staff, riders and drivers…")
            self.create_staff()
            self.create_riders()
            self.create_drivers()
            self.create_promos()
            self.surge_history()
            self.history()
            self.finish()
        self.welcome()
        self.stats["ledger_balanced"] = int(payments.verify_ledger()["balanced"])
        return self.stats


def demo_already_seeded() -> bool:
    return get_user_model().objects.filter(email="admin@ridepulse.dev").exists()
