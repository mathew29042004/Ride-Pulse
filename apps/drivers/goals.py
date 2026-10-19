"""Driver daily goals and "going home" mode.

Goals: completing N trips in a day pays a bonus from the platform's promotions budget (5 trips:
₹75, 10 trips: another ₹125 by default), once per tier per day, straight into the wallet.

Going home: with a home location set, a driver can ask for trips that take them closer to home
(drop-off at least 1 km nearer home than they are now), for an hour, twice a day. It switches
itself off when a trip ends within 1 km of home.
"""

from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.conf import driver_goals, going_home_rules
from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.geo.distance import haversine_km
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import DriverGoalReward, DriverProfile

HOMEWARD_GAIN_KM = 1.0
ARRIVED_HOME_KM = 1.0


def _today(at: datetime) -> date:
    return timezone.localtime(at).date()


def trips_today(driver: DriverProfile, at: datetime | None = None) -> int:
    from apps.rides.models import Trip, TripStatus

    day = _today(at or timezone.now())
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return Trip.objects.filter(
        driver=driver, status=TripStatus.COMPLETED, completed_at__gte=start
    ).count()


def progress(driver: DriverProfile, at: datetime | None = None) -> dict:
    at = at or timezone.now()
    day = _today(at)
    done = trips_today(driver, at)
    paid = set(driver.goal_rewards.filter(day=day).values_list("trips_target", flat=True))
    tiers = [
        {"trips": trips, "bonus": str(bonus), "reached": trips in paid or done >= trips}
        for trips, bonus in driver_goals()
    ]
    earned = sum((bonus for trips, bonus in driver_goals() if trips in paid), 0)
    from django.db.models import Sum

    from apps.rides.models import Trip, TripStatus

    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    takings = (
        Trip.objects.filter(
            driver=driver, status=TripStatus.COMPLETED, completed_at__gte=start
        ).aggregate(s=Sum("driver_earning"))["s"]
        or 0
    )
    return {
        "date": day,
        "completed_today": done,
        "tiers": tiers,
        "earned_today": str(earned),
        "earnings_today": str(takings + earned),
        "earnings_goal": driver.daily_earnings_goal,
    }


def set_earnings_goal(driver: DriverProfile, amount: int) -> DriverProfile:
    from apps.core.exceptions import BusinessRuleViolation

    if not 0 <= int(amount) <= 20000:
        raise BusinessRuleViolation("Set a goal between ₹0 and ₹20,000.", field="amount")
    driver.daily_earnings_goal = int(amount)
    driver.save(update_fields=["daily_earnings_goal", "updated_at"])
    return driver


def reward_goals(driver: DriverProfile, *, now: datetime | None = None) -> list[DriverGoalReward]:
    """Pay any daily goal the driver has just reached (called after each completed trip)."""
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post

    now = now or timezone.now()
    day, done = _today(now), trips_today(driver, now)
    rewards = []
    for trips, bonus in driver_goals():
        if done < trips:
            continue
        try:
            with transaction.atomic():
                reward = DriverGoalReward.objects.create(
                    driver=driver, day=day, trips_target=trips, bonus=bonus
                )
                post(
                    TransactionKind.DRIVER_BONUS,
                    [(accounts.PLATFORM_PROMOTIONS, -bonus), (ensure_wallet(driver.user), bonus)],
                    description=f"Daily goal: {trips} trips on {day:%d %b}",
                    at=now,
                )
        except IntegrityError:
            continue  # already paid today
        rewards.append(reward)
        notify(
            driver.user,
            f"Goal reached: ₹{bonus} bonus!",
            f"You completed {trips} trips today. The bonus is in your wallet.",
            level=Level.SUCCESS,
            link="/drive/earnings",
        )
    return rewards


# --- Going home ------------------------------------------------------------------------------


def set_home(driver: DriverProfile, *, lat: float, lng: float, address: str = "") -> DriverProfile:
    driver.home_lat, driver.home_lng, driver.home_address = lat, lng, address[:255]
    driver.save(update_fields=["home_lat", "home_lng", "home_address", "updated_at"])
    return driver


def going_home_active(driver: DriverProfile, at: datetime | None = None) -> bool:
    at = at or timezone.now()
    return bool(driver.going_home_until and driver.going_home_until > at)


def uses_left(driver: DriverProfile, at: datetime | None = None) -> int:
    per_day, _ = going_home_rules()
    used = driver.going_home_uses if driver.going_home_day == _today(at or timezone.now()) else 0
    return max(per_day - used, 0)


def set_going_home(
    driver: DriverProfile, *, on: bool, now: datetime | None = None
) -> DriverProfile:
    now = now or timezone.now()
    if not on:
        driver.going_home_until = None
        driver.save(update_fields=["going_home_until", "updated_at"])
        return driver
    if driver.home_lat is None:
        raise BusinessRuleViolation("Set your home location first (Account).")
    if going_home_active(driver, now):
        return driver
    per_day, minutes = going_home_rules()
    if uses_left(driver, now) == 0:
        raise ConflictError(f"You've used going-home mode {per_day} times today.")
    today = _today(now)
    driver.going_home_uses = (driver.going_home_uses if driver.going_home_day == today else 0) + 1
    driver.going_home_day = today
    driver.going_home_until = now + timedelta(minutes=minutes)
    driver.save(
        update_fields=["going_home_uses", "going_home_day", "going_home_until", "updated_at"]
    )
    return driver


def heads_home(driver: DriverProfile, trip) -> bool:
    """Does this trip's drop-off bring a going-home driver at least 1 km closer to home?"""
    if driver.current_lat is None:
        return False
    now_km = haversine_km(driver.current_lat, driver.current_lng, driver.home_lat, driver.home_lng)
    after_km = haversine_km(trip.dropoff_lat, trip.dropoff_lng, driver.home_lat, driver.home_lng)
    return after_km <= now_km - HOMEWARD_GAIN_KM


def after_trip(driver: DriverProfile, trip, *, now: datetime) -> None:
    """Switch going-home off once a trip drops the driver near home."""
    if (
        going_home_active(driver, now)
        and haversine_km(trip.dropoff_lat, trip.dropoff_lng, driver.home_lat, driver.home_lng)
        <= ARRIVED_HOME_KM
    ):
        DriverProfile.objects.filter(pk=driver.pk).update(going_home_until=None)
        notify(driver.user, "You're home!", "Going-home mode is off. Drive safe.")
