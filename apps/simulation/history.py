"""Back-fill realistic trip history across every city, for analytics and the data platform.

Reuses the demo seeder's trip generator (real booking, dispatch, pricing, payments, ratings,
tips, tickets), run day by day through the past. Adds parcel deliveries too. It books trips
*in the past* through the real dispatcher, so the live simulator must be stopped first (live bot
drivers would otherwise be offered past trips); the command checks this.
"""

import contextlib
import random
from collections.abc import Callable
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.drivers import services as drivers_svc
from apps.drivers.models import Availability, DriverProfile, OnboardingStatus
from apps.geo.models import City
from apps.notifications import services as notifications
from apps.pricing.models import RideType
from apps.realtime import broadcast
from apps.riders.models import RiderProfile
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import OfferStatus, Trip

from .fleet_data import HOURLY_DEMAND
from .network import driver_target
from .seed import Seeder

PARCEL_SHARE = 0.07
DEMO_EMAILS = {"driver@ridepulse.dev", "rider@ridepulse.dev"}


class LiveSimulatorRunning(Exception):
    pass


class HistoryGenerator:
    def __init__(
        self,
        *,
        days: int = 60,
        trips_per_day: int = 300,
        seed: int = 11,
        fill_gaps: bool = False,
        log: Callable[[str], None] = print,
    ):
        self.fill_gaps = fill_gaps
        self.days = days
        self.trips_per_day = trips_per_day
        self.log = log
        self.rng = random.Random(seed)
        self.seeder = Seeder(days=days, trips_per_day=trips_per_day, seed=seed, log=log)
        self.stats: dict[str, int] = {}

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    # --- Setup ------------------------------------------------------------------------------

    def _check_live(self) -> None:
        online = DriverProfile.objects.filter(availability=Availability.ONLINE).count()
        if online:
            raise LiveSimulatorRunning(
                f"{online} drivers are online. Stop the live simulator (and the app's "
                "`make dev`) before generating history, or run with --force-offline."
            )

    def _prepare(self, force_offline: bool) -> None:
        if force_offline:
            for driver in DriverProfile.objects.filter(availability=Availability.ONLINE):
                with contextlib.suppress(DomainError):
                    drivers_svc.go_offline(driver)
        self._check_live()
        s = self.seeder
        s.cities = {c.slug: c for c in City.objects.filter(is_active=True)}
        s.ride_types = {rt.code: rt for rt in RideType.objects.all()}
        User = get_user_model()
        s.ops_manager = User.objects.filter(email="ops@ridepulse.dev").first()
        s.admin = User.objects.filter(is_superuser=True).order_by("pk").first()
        s.support_agent = (
            User.objects.filter(email="support@ridepulse.dev").first()
            or User.objects.filter(role="SUPPORT_AGENT").first()
        )
        s.riders = list(
            RiderProfile.objects.filter(
                is_blocked=False, user__email__endswith="@example.com"
            ).exclude(user__email__in=DEMO_EMAILS)
        )
        if not s.riders:
            raise DomainError("No bot riders. Run `manage.py grow_network` first.")
        s.demo_rider = s.riders[0]  # never book history for the real demo rider
        s.city_drivers = {slug: [] for slug in s.cities}
        drivers = (
            DriverProfile.objects.filter(
                onboarding_status=OnboardingStatus.APPROVED,
                availability=Availability.OFFLINE,
                city__slug__in=list(s.cities),
            )
            .exclude(user__email__in=DEMO_EMAILS)
            .select_related("city")
            .prefetch_related("vehicles__ride_type")
        )
        for driver in drivers:
            vehicle = driver.active_vehicle
            if vehicle is None:
                continue
            s.city_drivers[driver.city.slug].append(driver)
            s.profile[driver.pk] = {
                "quality": min(5.0, max(3.2, float(driver.rating) + self.rng.uniform(-0.2, 0.2))),
                "risk": self.rng.random() ** 2,
                "activity": self.rng.uniform(0.4, 1.6),
                "ride_type": vehicle.ride_type.code,
            }
        self.weights = {slug: driver_target(slug) for slug in s.cities}

    # --- Trips ---------------------------------------------------------------------------------

    def _parcel(self, at: datetime, slug: str) -> None:
        s, rng = self.seeder, self.rng
        city = s.cities[slug]
        bikes = [d for d in s._available(slug, "BIKE", at) if d.accepts_parcels]
        endpoints = s._endpoints(city)
        if not bikes or endpoints is None:
            return
        pickup, pickup_name, dropoff, dropoff_name = endpoints
        driver = rng.choice(bikes)
        s._online_near(driver, pickup, at - timedelta(seconds=60))
        trip = rides.request_trip(
            rider=rng.choice(s.riders),
            ride_type=s.ride_types["PARCEL"],
            pickup=pickup,
            dropoff=dropoff,
            pickup_address=pickup_name,
            dropoff_address=dropoff_name,
            payment_method="UPI",
            parcel={
                "recipient_name": s.fake.first_name(),
                "recipient_phone": f"9{rng.randrange(10**8, 10**9)}",
                "category": rng.choice(["DOCUMENTS", "FOOD", "KEYS", "CLOTHES", "ELECTRONICS"]),
                "weight_kg": rng.choice([0.5, 1, 2, 3, 5]),
            },
            now=at,
        )
        offer = trip.offers.filter(status=OfferStatus.PENDING).select_related("driver").first()
        if offer is None:
            dispatch.sweep(now=trip.dispatch_deadline + timedelta(seconds=1))
            s._offline(driver, at + timedelta(minutes=3))
            return
        t = at + timedelta(seconds=rng.randrange(5, 15))
        trip = dispatch.accept_offer(offer, driver=offer.driver, now=t)
        courier = trip.driver
        t_arrive = t + timedelta(minutes=float(offer.eta_minutes) * rng.uniform(0.8, 1.3))
        drivers_svc.update_location(courier, lat=pickup[0], lng=pickup[1], now=t_arrive)
        trip = rides.mark_arrived(trip, driver=courier, now=t_arrive)
        t_start = t_arrive + timedelta(minutes=rng.uniform(1, 4))
        trip = rides.start_trip(trip, driver=courier, otp=trip.otp, now=t_start)
        from .traffic import true_minutes

        t_end = t_start + timedelta(minutes=true_minutes(trip, t_start, rng))
        drivers_svc.update_location(courier, lat=dropoff[0], lng=dropoff[1], now=t_end)
        rides.complete_delivery(
            trip,
            driver=courier,
            delivery_code=trip.parcel.delivery_code,
            now=t_end,
            actual_distance_km=trip.estimated_distance_km,
            payer_reference="seed@upi",
        )
        s._offline(courier, t_end + timedelta(minutes=rng.randrange(1, 15)))
        if courier.pk != driver.pk:
            s._offline(driver, t_end)
        self.count("parcels")

    def _hour_counts(self, day) -> dict[int, int]:
        """Trips already in the database per local hour of ``day``."""
        from django.db.models import Count
        from django.db.models.functions import ExtractHour

        start = timezone.make_aware(datetime.combine(day, time.min))
        rows = (
            Trip.objects.filter(requested_at__gte=start, requested_at__lt=start + timedelta(days=1))
            .annotate(hour=ExtractHour("requested_at"))
            .values("hour")
            .annotate(n=Count("pk"))
        )
        return {r["hour"]: r["n"] for r in rows} or {-1: 0}

    def run(self, *, force_offline: bool = False) -> dict:
        self._prepare(force_offline)
        s, rng = self.seeder, self.rng
        today = timezone.localdate()
        events = []
        for d in range(self.days, 0, -1):  # up to yesterday: today belongs to the live app
            day = today - timedelta(days=d)
            factor = 1.15 if day.weekday() >= 5 else 1.0
            growth = 0.75 + 0.25 * (1 - d / self.days)  # the business grew over the period
            n = int(self.trips_per_day * factor * growth * rng.uniform(0.85, 1.15))
            existing = self._hour_counts(day) if self.fill_gaps else {}
            total_weight = sum(HOURLY_DEMAND)
            for _ in range(n):
                hour = rng.choices(range(24), weights=HOURLY_DEMAND)[0]
                if existing and existing.get(hour, 0) >= n * HOURLY_DEMAND[hour] / total_weight / 2:
                    continue  # this hour already has its trips
                at = timezone.make_aware(
                    datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)))
                )
                slug = rng.choices(list(self.weights), weights=list(self.weights.values()))[0]
                events.append((at, slug))
        events.sort()
        self.log(f"Generating {len(events)} trips over {self.days} days in {len(s.cities)} cities…")
        with notifications.muted(), broadcast.muted():
            for i, (at, slug) in enumerate(events, 1):
                try:
                    if rng.random() < PARCEL_SHARE:
                        self._parcel(at, slug)
                    else:
                        trip = s.one_trip(at, slug)
                        self.count("trips" if trip else "skipped")
                except DomainError:
                    self.count("skipped")
                if i % 500 == 0:
                    self.log(f"  {i}/{len(events)} ({at:%d %b})")
            # Leave nobody online at a past time.
            for driver in DriverProfile.objects.filter(availability=Availability.ONLINE):
                with contextlib.suppress(DomainError):
                    drivers_svc.go_offline(driver)
        self.stats.update({k: v for k, v in s.stats.items() if k not in self.stats})
        return self.stats
