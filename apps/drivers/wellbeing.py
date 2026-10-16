"""Driver Wellbeing: rest after long driving stretches, a daily limit and a weekly day off.

A *stretch* is time online with no real rest: online sessions joined by gaps shorter than the
break length (20 minutes) count as one. After 6 hours the driver gets no new offers; when the
current trip ends (or right away if idle) they're taken offline for a 20-minute break and can't
come back early. They're warned 30 minutes before. Taking a proper break after 4+ hours pays a
small rest bonus, once a day.

On top of that, **no more than 12 hours online in any 24**: at the limit the driver is taken
offline for 8 hours (Indian transport-worker rules cap a driver's working day; tired driving is
the risk). After **6 days** with 4+ hours online in a week, they're nudged to take a day off. On
a break, the app suggests nearby places to rest: malls and stations (parking, food, toilets) and
EV chargers.
"""

from datetime import datetime, timedelta

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.core.conf import wellbeing_rules
from apps.core.exceptions import BusinessRuleViolation
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import Availability, DriverProfile, DriverSession

LOOKBACK = timedelta(hours=24)


def _minutes(delta: timedelta) -> int:
    return max(int(delta.total_seconds() // 60), 0)


def stretch(driver: DriverProfile, now: datetime) -> tuple[datetime | None, datetime | None]:
    """(start, end) of the latest driving stretch; end is ``now`` while online. ``(None, None)``
    if the driver has rested since."""
    brk = timedelta(minutes=wellbeing_rules()["break_minutes"])
    sessions = list(
        DriverSession.objects.filter(driver=driver, started_at__gte=now - LOOKBACK)
        .order_by("-started_at")
        .values_list("started_at", "ended_at")
    )
    if not sessions:
        return None, None
    start, end = sessions[0]
    end = end or now
    if now - end >= brk:
        return None, None
    for earlier_start, earlier_end in sessions[1:]:
        if earlier_end is None or start - earlier_end >= brk:
            break
        start = earlier_start
    return start, end


def driving_minutes(driver: DriverProfile, now: datetime) -> int:
    start, end = stretch(driver, now)
    return _minutes(end - start) if start else 0


def online_minutes(driver: DriverProfile, since: datetime, now: datetime) -> int:
    """Minutes online between ``since`` and ``now`` (sessions clipped to the window)."""
    total = 0
    for started, ended in (
        DriverSession.objects.filter(driver=driver)
        .filter(models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=since), started_at__lt=now)
        .values_list("started_at", "ended_at")
    ):
        total += _minutes(min(ended or now, now) - max(started, since))
    return total


def daily_minutes(driver: DriverProfile, now: datetime) -> int:
    return online_minutes(driver, now - timedelta(hours=24), now)


def days_driven(driver: DriverProfile, now: datetime) -> int:
    """Days in the last 7 with at least 4 hours online."""
    rules = wellbeing_rules()
    today = timezone.localdate(now)
    days = 0
    for back in range(7):
        day = today - timedelta(days=back)
        start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        end = min(start + timedelta(days=1), now)
        if online_minutes(driver, start, end) >= rules["day_counts_after_minutes"]:
            days += 1
    return days


def needs_break(driver: DriverProfile, now: datetime) -> bool:
    rules = wellbeing_rules()
    return (
        driving_minutes(driver, now) >= rules["max_minutes"]
        or daily_minutes(driver, now) >= rules["daily_max_minutes"]
    )


def rest_stops(driver: DriverProfile, *, limit: int = 3) -> list[dict]:
    """Nearby places to rest: malls, stations and airports (parking, food, toilets) and EV
    chargers for electric cars."""
    from apps.fleet.models import ChargingStation
    from apps.geo.distance import haversine_km
    from apps.geo.models import Landmark

    if driver.current_lat is None:
        return []
    here = (driver.current_lat, driver.current_lng)
    places = [
        (haversine_km(*here, p.lat, p.lng), p.name, p.get_category_display())
        for p in Landmark.objects.filter(
            city_id=driver.city_id, category__in=["MALL", "TRANSIT", "AIRPORT"]
        )
    ]
    vehicle = driver.active_vehicle
    if vehicle is not None and vehicle.fuel_type == "EV":
        places += [
            (haversine_km(*here, c.lat, c.lng), c.name, "EV charger")
            for c in ChargingStation.objects.filter(city_id=driver.city_id)
        ]
    return [
        {"name": name, "kind": kind, "km": round(km, 1)}
        for km, name, kind in sorted(places)[:limit]
    ]


def status(driver: DriverProfile, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    rules = wellbeing_rules()
    minutes = driving_minutes(driver, now)
    on_break = bool(driver.break_until and driver.break_until > now)
    today = daily_minutes(driver, now)
    return {
        "daily_minutes": today,
        "daily_limit_minutes": rules["daily_max_minutes"],
        "days_driven_this_week": days_driven(driver, now),
        "week_days_limit": rules["week_days_limit"],
        "rest_stops": rest_stops(driver) if on_break or needs_break(driver, now) else [],
        "driving_minutes": minutes,
        "limit_minutes": rules["max_minutes"],
        "minutes_left": max(rules["max_minutes"] - minutes, 0),
        "break_minutes": rules["break_minutes"],
        "on_break_until": driver.break_until if on_break else None,
        "rest_bonus": str(rules["rest_bonus"]),
        "rest_bonus_after_minutes": rules["bonus_after_minutes"],
        "rest_bonus_paid_today": driver.rest_bonus_on == timezone.localdate(now),
    }


def check_can_go_online(driver: DriverProfile, now: datetime) -> None:
    """Called by ``go_online``: no coming back before the break is over."""
    if driver.break_until and driver.break_until > now:
        raise BusinessRuleViolation(
            "You're on a rest break after a long drive. You can go online again at "
            f"{timezone.localtime(driver.break_until):%I:%M %p}."
        )
    start, end = stretch(driver, now)
    rules = wellbeing_rules()
    if daily_minutes(driver, now) >= rules["daily_max_minutes"]:
        last = DriverSession.objects.filter(driver=driver, ended_at__isnull=False).first()
        back = (last.ended_at if last else now) + timedelta(minutes=rules["long_rest_minutes"])
        if back > now:
            raise BusinessRuleViolation(
                f"You've been online {rules['daily_max_minutes'] // 60} hours in the last day. "
                f"Rest for {rules['long_rest_minutes'] // 60} hours; you can go online again at "
                f"{timezone.localtime(back):%a %I:%M %p}."
            )
    if start and _minutes(end - start) >= rules["max_minutes"]:
        back = end + timedelta(minutes=rules["break_minutes"])
        raise BusinessRuleViolation(
            f"You've driven {_minutes(end - start) // 60} hours. Rest for "
            f"{rules['break_minutes']} minutes; you can go online again at "
            f"{timezone.localtime(back):%I:%M %p}."
        )


def reward_rest(driver: DriverProfile, now: datetime) -> bool:
    """Called by ``go_online``: a proper break after a long stretch earns the rest bonus."""
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post

    rules = wellbeing_rules()
    today = timezone.localdate(now)
    if driver.rest_bonus_on == today:
        return False
    last = DriverSession.objects.filter(driver=driver, ended_at__isnull=False).first()
    if last is None or now - last.ended_at < timedelta(minutes=rules["break_minutes"]):
        return False
    start, end = stretch(driver, last.ended_at)
    if not start or _minutes(end - start) < rules["bonus_after_minutes"]:
        return False
    bonus = rules["rest_bonus"]
    try:
        with transaction.atomic():
            updated = DriverProfile.objects.filter(pk=driver.pk).exclude(rest_bonus_on=today)
            if not updated.update(rest_bonus_on=today):
                return False
            post(
                TransactionKind.DRIVER_BONUS,
                [(accounts.PLATFORM_PROMOTIONS, -bonus), (ensure_wallet(driver.user), bonus)],
                description=f"Rest bonus: break after {_minutes(end - start) // 60}h driving",
                at=now,
            )
    except IntegrityError:
        return False
    driver.rest_bonus_on = today
    notify(
        driver.user,
        f"₹{bonus} rest bonus",
        "Thanks for taking a proper break. Safe driving!",
        level=Level.SUCCESS,
        link="/drive/earnings",
    )
    return True


def enforce(driver: DriverProfile, now: datetime | None = None) -> str:
    """Warn near the limit; at the limit, take an idle driver offline for their break.
    Returns what happened: "", "warned" or "break"."""
    from . import services

    now = now or timezone.now()
    driver = DriverProfile.objects.get(pk=driver.pk)
    if driver.availability != Availability.ONLINE:
        return ""
    rules = wellbeing_rules()
    start, _ = stretch(driver, now)
    minutes = driving_minutes(driver, now)
    if daily_minutes(driver, now) >= rules["daily_max_minutes"]:
        services.go_offline(driver, now=now)
        until = now + timedelta(minutes=rules["long_rest_minutes"])
        DriverProfile.objects.filter(pk=driver.pk).update(break_until=until)
        notify(
            driver.user,
            "That's 12 hours today: time to rest",
            f"You can go online again at {timezone.localtime(until):%a %I:%M %p}. "
            "Tired driving is the biggest risk on the road.",
            level=Level.WARNING,
            link="/drive",
        )
        return "break"
    if minutes >= rules["max_minutes"]:
        services.go_offline(driver, now=now)
        until = now + timedelta(minutes=rules["break_minutes"])
        DriverProfile.objects.filter(pk=driver.pk).update(break_until=until)
        notify(
            driver.user,
            "Time for a break",
            f"You've driven {minutes // 60} hours. Rest for {rules['break_minutes']} minutes: "
            f"you can go online again at {timezone.localtime(until):%I:%M %p}.",
            level=Level.WARNING,
            link="/drive",
        )
        return "break"
    warned_this_stretch = driver.break_warned_at and start and driver.break_warned_at >= start
    if minutes >= rules["max_minutes"] - rules["warn_minutes"] and not warned_this_stretch:
        DriverProfile.objects.filter(pk=driver.pk).update(break_warned_at=now)
        notify(
            driver.user,
            f"Break in {rules['max_minutes'] - minutes} minutes",
            "You've been driving a long time. Finish your next trip and take a short rest.",
            level=Level.INFO,
            link="/drive",
        )
        return "warned"
    return ""


def nudge_day_off(driver: DriverProfile, now: datetime) -> bool:
    """Once a week, after 6 working days, suggest a day off (a nudge, not a block)."""
    from apps.notifications.models import Notification

    rules = wellbeing_rules()
    title = "Take a day off this week"
    if days_driven(driver, now) < rules["week_days_limit"]:
        return False
    if Notification.objects.filter(
        user=driver.user, title=title, created_at__gte=now - timedelta(days=7)
    ).exists():
        return False
    notify(
        driver.user,
        title,
        f"You've driven {rules['week_days_limit']} days in a row. A full day's rest keeps you "
        "sharp and safe.",
        level=Level.INFO,
        link="/drive",
    )
    return True


def sweep(now: datetime | None = None) -> dict:
    """Every few minutes: enforce breaks and the daily limit for idle online drivers, and
    nudge drivers who haven't had a day off."""
    now = now or timezone.now()
    counts = {"warned": 0, "break": 0, "day_off_nudges": 0}
    for driver in DriverProfile.objects.filter(availability=Availability.ONLINE).select_related(
        "user"
    ):
        outcome = enforce(driver, now)
        if outcome:
            counts[outcome] += 1
        if now.minute < 10 and nudge_day_off(driver, now):  # checked about once an hour
            counts["day_off_nudges"] += 1
    return counts
