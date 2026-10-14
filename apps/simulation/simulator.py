"""Live marketplace simulator: bot drivers and riders acting in real time.

Run ``python manage.py simulate`` next to the web server. Bots use the same services as the
apps, so everything they do shows up on the live map, in the rider and driver apps and in
analytics. The simulator also runs the periodic jobs Celery beat would run in production
(dispatch sweep, surge recompute), so the platform works without Redis.

When you book a ride as the demo rider, the nearest bot driver picks you up: it drives to you,
"hears" your ride PIN, takes you to your drop and completes the trip.
"""

import math
import random
import time as clock
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from django.db import close_old_connections
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.drivers import services as drivers_svc
from apps.drivers.models import Availability, DriverProfile, OnboardingStatus
from apps.geo.distance import arc, bearing_degrees, haversine_km, move_along, move_towards, offset
from apps.geo.google import decode_polyline
from apps.geo.models import City
from apps.payments import services as payments
from apps.pricing import services as pricing
from apps.pricing.models import RideType
from apps.riders.models import RiderProfile
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import (
    ACTIVE_STATUSES,
    OfferStatus,
    Trip,
    TripMessage,
    TripOffer,
    TripStatus,
)

from .fleet_data import PAYMENT_WEIGHTS, RIDE_TYPE_WEIGHTS

DEMO_EMAILS = {"driver@ridepulse.dev", "rider@ridepulse.dev"}
BOT_RIDER_DOMAIN = "@example.com"  # the seeder's synthetic riders


@dataclass
class BotDriver:
    driver_id: int
    waypoint: tuple[float, float] | None = None
    next_action_at: datetime | None = None
    accept_rate: float = 0.88


@dataclass
class Simulator:
    city_slugs: list[str]
    drivers_per_city: int = 18
    request_interval: float = 25.0  # average seconds between bot ride requests per city
    speedup: float = 4.0  # bots drive this many times faster than real traffic
    tick_seconds: float = 2.0
    seed: int | None = None
    log: callable = print
    bots: dict[int, BotDriver] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.cities = list(City.objects.filter(slug__in=self.city_slugs, is_active=True))
        self.ride_types = {rt.code: rt for rt in RideType.objects.all()}
        self.last_surge = 0.0
        self.next_request: dict[int, float] = {}
        # Adopt bots left mid-trip by a previous run, so their riders aren't stranded.
        for pk in (
            DriverProfile.objects.filter(city__in=self.cities)
            .exclude(availability=Availability.OFFLINE)
            .exclude(user__email__in=DEMO_EMAILS)
            .values_list("pk", flat=True)
        ):
            self.bots[pk] = BotDriver(pk)

    def bump(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    # --- Bot drivers ----------------------------------------------------------------------

    def recruit(self) -> None:
        """Keep a pool of approved bot drivers online in each city."""
        for city in self.cities:
            mine = [b for b in self.bots.values() if b.driver_id in self._city_driver_ids(city)]
            missing = self.drivers_per_city - len(mine)
            if missing <= 0:
                continue
            candidates = list(
                DriverProfile.objects.filter(
                    city=city,
                    onboarding_status=OnboardingStatus.APPROVED,
                    availability=Availability.OFFLINE,
                )
                .exclude(user__email__in=DEMO_EMAILS)
                .exclude(pk__in=list(self.bots))
                .order_by("?")[:missing]
            )
            for driver in candidates:
                zone = self.rng.choice(list(city.zones.all()))
                lat, lng = self._jitter(zone.center_lat, zone.center_lng, zone.radius_km)
                try:
                    if payments.wallet_balance(driver.user) < -300:
                        payments.pay_dues(driver.user, method="UPI", payer_reference="bot@upi")
                    drivers_svc.go_online(driver, lat=lat, lng=lng)
                except DomainError:
                    continue
                self.bots[driver.pk] = BotDriver(driver.pk, accept_rate=self.rng.uniform(0.8, 0.97))
                self.bump("drivers_online")

    def _city_driver_ids(self, city: City) -> set[int]:
        if not hasattr(self, "_city_cache"):
            self._city_cache = {}
        if city.pk not in self._city_cache:
            self._city_cache[city.pk] = set(
                DriverProfile.objects.filter(city=city).values_list("pk", flat=True)
            )
        return self._city_cache[city.pk]

    def _jitter(self, lat: float, lng: float, radius_km: float) -> tuple[float, float]:
        angle = self.rng.uniform(0, 2 * math.pi)
        distance = radius_km * math.sqrt(self.rng.random())
        return offset(lat, lng, distance * math.cos(angle), distance * math.sin(angle))

    def _step_km(self) -> float:
        speed_kmh = 24 * self.speedup
        return speed_kmh * self.tick_seconds / 3600

    def _drive(
        self,
        driver: DriverProfile,
        target: tuple[float, float],
        path: list[tuple[float, float]] | None = None,
    ) -> bool:
        if path:
            lat, lng, arrived = move_along(
                path, driver.current_lat, driver.current_lng, self._step_km()
            )
        else:
            lat, lng, arrived = move_towards(
                driver.current_lat, driver.current_lng, *target, self._step_km()
            )
        heading = bearing_degrees(driver.current_lat, driver.current_lng, lat, lng)
        drivers_svc.update_location(driver, lat=lat, lng=lng, heading=heading, speed_kmh=24.0)
        return arrived

    def act(self, bot: BotDriver, now: datetime) -> None:
        driver = (
            DriverProfile.objects.select_related("user", "city").filter(pk=bot.driver_id).first()
        )
        if driver is None or driver.availability == Availability.OFFLINE:
            self.bots.pop(bot.driver_id, None)
            return
        trip = (
            Trip.objects.filter(driver=driver, status__in=ACTIVE_STATUSES)
            .select_related("rider__user", "ride_type", "city", "pickup_zone", "dropoff_zone")
            .first()
        )
        if trip is None:
            offer = (
                TripOffer.objects.filter(driver=driver, status=OfferStatus.PENDING)
                .select_related("trip__rider__user")
                .first()
            )
            if offer:
                self._respond(bot, driver, offer, now)
            else:
                self._wander(bot, driver)
            return
        self._reply_to_chat(trip, driver, now)
        if trip.status == TripStatus.DRIVER_ASSIGNED:
            if self._drive(driver, (trip.pickup_lat, trip.pickup_lng)):
                rides.mark_arrived(trip, driver=driver)
                bot.next_action_at = now + timedelta(seconds=self.rng.uniform(4, 10))
        elif trip.status == TripStatus.DRIVER_ARRIVED:
            if bot.next_action_at is None or now >= bot.next_action_at:
                # The bot "hears" the PIN from the rider, exactly as a real driver would.
                rides.start_trip(trip, driver=driver, otp=trip.otp)
                bot.next_action_at = None
        elif trip.status == TripStatus.IN_PROGRESS and self._drive(
            driver, (trip.dropoff_lat, trip.dropoff_lng), self._route(trip)
        ):
            trip = rides.complete_trip(
                trip,
                driver=driver,
                telemetry={
                    "harsh_brakes": self.rng.choice([0, 0, 0, 1, 2]),
                    "harsh_accelerations": self.rng.choice([0, 0, 1]),
                    "speeding_seconds": self.rng.choice([0, 0, 0, 20, 45]),
                },
                payer_reference="bot@upi",
            )
            self.bump("trips_completed")
            if self.rng.random() < 0.7:
                rides.rate_trip(trip, user=driver.user, stars=self.rng.choice([5, 5, 5, 4]))
            if trip.rider.user.email not in DEMO_EMAILS and self.rng.random() < 0.8:
                rides.rate_trip(
                    trip, user=trip.rider.user, stars=self.rng.choice([5, 5, 5, 4, 4, 3])
                )
            bot.waypoint = None

    CHAT_REPLIES = {
        TripStatus.DRIVER_ASSIGNED: [
            "On my way, see you in a few minutes!",
            "Coming, a bit of traffic here.",
            "Okay sir, reaching soon.",
        ],
        TripStatus.DRIVER_ARRIVED: [
            "I'm at the pickup point.",
            "Waiting near the main gate.",
        ],
        TripStatus.IN_PROGRESS: ["Sure.", "Okay, no problem.", "Noted 👍"],
    }

    def _reply_to_chat(self, trip: Trip, driver: DriverProfile, now: datetime) -> None:
        """Bots answer the rider's latest message after a short, human-looking pause."""
        last = trip.messages.order_by("-created_at", "-id").first()
        if last is None or last.sender != TripMessage.Sender.RIDER:
            return
        if (now - last.created_at).total_seconds() < self.rng.uniform(3, 6):
            return
        replies = self.CHAT_REPLIES.get(trip.status)
        if replies:
            rides.send_message(trip, user=driver.user, body=self.rng.choice(replies))

    @staticmethod
    def _route(trip: Trip) -> list[tuple[float, float]]:
        """The line the rider's app draws: the road route if known, else the same arc."""
        if trip.route_polyline:
            return decode_polyline(trip.route_polyline)
        path: list[tuple[float, float]] = []
        for start, end in pairwise(trip.waypoints):  # through the stop, if there is one
            leg = arc(start, end)
            path.extend(leg[1:] if path else leg)
        return path

    def _respond(
        self, bot: BotDriver, driver: DriverProfile, offer: TripOffer, now: datetime
    ) -> None:
        if bot.next_action_at is None:  # think for a few seconds, like a person would
            bot.next_action_at = now + timedelta(seconds=self.rng.uniform(2, 6))
            return
        if now < bot.next_action_at:
            return
        bot.next_action_at = None
        is_demo_rider = offer.trip.rider.user.email in DEMO_EMAILS
        try:
            # A boost or a promised tip makes a driver likelier to say yes (+1% per rupee).
            sweetener = float(offer.trip.boost_amount + offer.trip.tip_pledged) / 100
            if is_demo_rider or self.rng.random() < min(0.99, bot.accept_rate + sweetener):
                dispatch.accept_offer(offer, driver=driver)
                self.bump("offers_accepted")
            else:
                dispatch.decline_offer(offer, driver=driver)
                self.bump("offers_declined")
        except DomainError:
            pass

    def _wander(self, bot: BotDriver, driver: DriverProfile) -> None:
        """Idle drivers cruise towards busy zones, like real drivers chasing demand."""
        if (
            bot.waypoint is None
            or haversine_km(driver.current_lat, driver.current_lng, *bot.waypoint) < 0.1
        ):
            zones = list(driver.city.zones.all())
            zone = self.rng.choices(zones, weights=[z.demand_weight for z in zones])[0]
            bot.waypoint = self._jitter(zone.center_lat, zone.center_lng, zone.radius_km)
        lat, lng, _ = move_towards(
            driver.current_lat, driver.current_lng, *bot.waypoint, self._step_km() * 0.5
        )
        drivers_svc.update_location(
            driver,
            lat=lat,
            lng=lng,
            heading=bearing_degrees(driver.current_lat, driver.current_lng, lat, lng),
        )

    # --- Bot riders -----------------------------------------------------------------------

    @staticmethod
    def pick_bot_rider() -> RiderProfile | None:
        """A random idle synthetic rider. Never a real sign-up or a load-test account: the bots
        must not book rides (or spend wallet money) for actual people."""
        return (
            RiderProfile.objects.filter(is_blocked=False, user__email__endswith=BOT_RIDER_DOMAIN)
            .exclude(user__email__in=DEMO_EMAILS)
            .exclude(trips__status__in=ACTIVE_STATUSES)
            .order_by("?")
            .first()
        )

    def maybe_request(self, city: City, now_ts: float) -> None:
        due = self.next_request.get(city.pk, now_ts)
        if now_ts < due:
            return
        self.next_request[city.pk] = now_ts + self.rng.expovariate(1 / self.request_interval)
        rider = self.pick_bot_rider()
        if rider is None:
            return
        zones = list(city.zones.all())
        a, b = self.rng.choices(zones, weights=[z.demand_weight for z in zones], k=2)
        pickup = self._jitter(a.center_lat, a.center_lng, a.radius_km * 0.8)
        dropoff = self._jitter(b.center_lat, b.center_lng, b.radius_km * 0.8)
        if haversine_km(*pickup, *dropoff) < 1.5:
            return
        method = self.rng.choices(list(PAYMENT_WEIGHTS), weights=list(PAYMENT_WEIGHTS.values()))[0]
        try:
            if payments.wallet_balance(rider.user) < 0:
                payments.pay_dues(rider.user, method="UPI", payer_reference="bot@upi")
            rides.request_trip(
                rider=rider,
                ride_type=self.ride_types[
                    self.rng.choices(
                        list(RIDE_TYPE_WEIGHTS), weights=list(RIDE_TYPE_WEIGHTS.values())
                    )[0]
                ],
                pickup=pickup,
                dropoff=dropoff,
                pickup_address=a.name,
                dropoff_address=b.name,
                payment_method="UPI" if method == "WALLET" else method,
            )
            self.bump("requests")
        except DomainError:
            self.bump("request_rejected")

    def rider_cancellations(self) -> None:
        """A few impatient bot riders give up while waiting."""
        cutoff = timezone.now() - timedelta(seconds=90)
        for trip in (
            Trip.objects.filter(status=TripStatus.REQUESTED, requested_at__lt=cutoff)
            .exclude(rider__user__email__in=DEMO_EMAILS)
            .select_related("rider__user")[:5]
        ):
            if self.rng.random() < 0.15:
                try:
                    rides.cancel_trip(trip, user=trip.rider.user, reason="Took too long")
                    self.bump("rider_cancelled")
                except DomainError:
                    pass

    # --- Main loop ------------------------------------------------------------------------

    def tick(self) -> None:
        now = timezone.now()
        self.recruit()
        for city in self.cities:
            self.maybe_request(city, clock.monotonic())
        for bot in list(self.bots.values()):
            try:
                self.act(bot, now)
            except DomainError as exc:
                self.log(f"  bot {bot.driver_id}: {exc.message}")
        dispatch.sweep()
        rides.dispatch_scheduled_rides()
        self.rider_cancellations()
        if clock.monotonic() - self.last_surge > 60:
            pricing.recompute_surge()
            self.last_surge = clock.monotonic()

    def run(self, *, duration: float | None = None, report_every: float = 30) -> None:
        started = last_report = clock.monotonic()
        try:
            while duration is None or clock.monotonic() - started < duration:
                close_old_connections()
                begun = clock.monotonic()
                self.tick()
                if clock.monotonic() - last_report >= report_every:
                    active = Trip.objects.filter(status__in=ACTIVE_STATUSES).count()
                    self.log(
                        f"[{timezone.localtime():%H:%M:%S}] {len(self.bots)} bot drivers · "
                        f"{active} active trips · {self.stats}"
                    )
                    last_report = clock.monotonic()
                clock.sleep(max(0.0, self.tick_seconds - (clock.monotonic() - begun)))
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Send bot drivers home (they'd otherwise linger as stale 'online' cars)."""
        for driver in DriverProfile.objects.filter(
            pk__in=list(self.bots), availability=Availability.ONLINE
        ):
            with suppress(DomainError):
                drivers_svc.go_offline(driver)
