"""Demo tours: completed ones from the last month (run through the real trip flow, so fares,
payments and ratings are genuine), upcoming bookings across every city, and a tour each for the
demo rider and driver logins."""

import random
from contextlib import suppress
from datetime import datetime, timedelta

from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.drivers import services as drivers
from apps.drivers.models import Availability, DriverProfile
from apps.notifications import services as notifications
from apps.pricing.models import RideType
from apps.realtime import broadcast
from apps.riders.models import RiderProfile
from apps.rides import services as rides

from . import services
from .models import BookingStatus, TourBooking, TourPackage

REVIEWS = {
    5: [
        "Wonderful day, the driver knew every place",
        "Perfectly planned, worth it",
        "Driver waited patiently at every stop",
        "Great value for the whole family",
    ],
    4: ["Good trip, a little rushed at the last stop", "Nice car and a careful driver"],
    3: ["Okay, the AC could have been better", "Long drive but the places were lovely"],
}


def _at(day, start, rng) -> datetime:
    return timezone.make_aware(datetime.combine(day, start)) + timedelta(
        minutes=rng.choice([-30, 0, 0, 30, 60])
    )


def _types():
    return {t.code: t for t in RideType.objects.filter(code__in=services.TOUR_TYPES)}


def _run(booking: TourBooking, rng: random.Random) -> bool:
    """Drive a booked tour start to finish at its own (past) time."""
    driver = booking.driver
    depart = booking.depart_at
    t = depart - timedelta(minutes=20)
    with suppress(DomainError):
        if driver.availability != Availability.OFFLINE:
            drivers.go_offline(driver, now=t - timedelta(minutes=1))
        trip = services.start(
            booking, driver=driver, lat=booking.pickup_lat, lng=booking.pickup_lng, now=t
        )
        drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=depart)
        trip = rides.mark_arrived(trip, driver=driver, now=depart)
        trip = rides.start_trip(
            trip, driver=driver, otp=trip.otp, now=depart + timedelta(minutes=3)
        )
        clock = depart + timedelta(minutes=3)
        for stop in booking.package.stops.all():
            clock += timedelta(minutes=rng.randint(30, 90))
            services.mark_stop(booking, driver=driver, order=stop.order, event="arrived", now=clock)
            clock += timedelta(minutes=stop.minutes)
            booking = services.mark_stop(
                booking, driver=driver, order=stop.order, event="left", now=clock
            )
        clock += timedelta(minutes=rng.randint(40, 120))
        drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=clock)
        rides.complete_trip(
            trip,
            driver=driver,
            actual_distance_km=trip.estimated_distance_km,
            now=clock,
            payer_reference="tour@upi",
        )
        drivers.go_offline(driver, now=clock + timedelta(minutes=1))
        booking.refresh_from_db()
        stars = rng.choices([5, 4, 3], [70, 24, 6])[0]
        if rng.random() < 0.8:
            services.rate(
                booking, user=booking.rider.user, stars=stars, review=rng.choice(REVIEWS[stars])
            )
        return True
    return False


def seed(*, seed: int = 31, log=print, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    # Each part runs once (so an interrupted seed can simply be run again).
    have_past = TourBooking.objects.filter(depart_at__lt=now).exists()
    have_upcoming = TourBooking.objects.filter(depart_at__gte=now).exists()
    if have_past and have_upcoming:
        return {"tours": 0}
    rng = random.Random(seed)
    types = _types()
    packages = list(TourPackage.objects.filter(is_active=True).select_related("city"))
    riders = list(
        RiderProfile.objects.filter(is_blocked=False)
        .exclude(user__email__endswith="@ridepulse.dev")
        .select_related("user")[:600]
    )
    if not packages or not riders:
        return {"tours": 0}
    log("Tour packages: last month's tours, upcoming bookings and drivers assigned ahead…")
    stats = {"tours_completed": 0, "tours_upcoming": 0, "tours_cancelled": 0}
    with notifications.muted(), broadcast.muted():
        # A month of completed tours, spread over the cities.
        for _ in range(0 if have_past else 90):
            package = rng.choice(packages)
            day = timezone.localdate(now) - timedelta(days=rng.randint(2, 30))
            depart = _at(day, package.start_time, rng)
            code = rng.choices(["MINI", "SEDAN", "SUV"], [45, 35, 20])[0]
            rider = rng.choice(riders)
            with suppress(DomainError):
                booking = services.book(
                    rider=rider,
                    package=package,
                    ride_type=types[code],
                    depart_at=depart,
                    pickup=(
                        package.city.center_lat + rng.uniform(-0.03, 0.03),
                        package.city.center_lng + rng.uniform(-0.03, 0.03),
                    ),
                    pickup_address="Home",
                    group_size=rng.randint(1, 4),
                    now=depart - timedelta(days=rng.randint(1, 10)),
                )
                booking = services.assign(booking, now=depart - timedelta(hours=20))
                if booking.status == BookingStatus.ASSIGNED and _run(booking, rng):
                    stats["tours_completed"] += 1
        # The next three weeks: booked, and assigned when within a day.
        for _ in range(0 if have_upcoming else 140):
            package = rng.choice(packages)
            day = timezone.localdate(now) + timedelta(days=rng.randint(1, 21))
            code = rng.choices(["MINI", "SEDAN", "SUV"], [45, 35, 20])[0]
            with suppress(DomainError):
                booking = services.book(
                    rider=rng.choice(riders),
                    package=package,
                    ride_type=types[code],
                    depart_at=_at(day, package.start_time, rng),
                    pickup=(
                        package.city.center_lat + rng.uniform(-0.03, 0.03),
                        package.city.center_lng + rng.uniform(-0.03, 0.03),
                    ),
                    pickup_address="Home",
                    group_size=rng.randint(1, 4),
                    now=now,
                )
                stats["tours_upcoming"] += 1
                if rng.random() < 0.06:
                    services.cancel(booking, user=booking.rider.user, now=now)
                    stats["tours_cancelled"] += 1
        if not have_upcoming:
            stats.update(_demo_logins(now, types))
    log(f"  {stats}")
    return stats


def _demo_logins(now: datetime, types: dict) -> dict:
    """rider@ has Mahabalipuram the day after tomorrow, with driver@ assigned to it."""
    rider = RiderProfile.objects.filter(user__email="rider@ridepulse.dev").first()
    driver = DriverProfile.objects.filter(user__email="driver@ridepulse.dev").first()
    package = TourPackage.objects.filter(slug="chennai-mahabalipuram-heritage").first()
    if not (rider and driver and package):
        return {}
    vehicle = driver.active_vehicle
    code = vehicle.ride_type.code if vehicle and vehicle.ride_type.code in types else "MINI"
    day = timezone.localdate(now) + timedelta(days=2)
    with suppress(DomainError):
        booking = services.book(
            rider=rider,
            package=package,
            ride_type=types[code],
            depart_at=timezone.make_aware(datetime.combine(day, package.start_time)),
            pickup=(13.0418, 80.2341),
            pickup_address="T. Nagar, Chennai",
            group_size=2,
            now=now,
        )
        TourBooking.objects.filter(pk=booking.pk).update(
            driver=driver, assigned_at=now, status=BookingStatus.ASSIGNED
        )
        return {"demo_tour": booking.reference}
    return {}
