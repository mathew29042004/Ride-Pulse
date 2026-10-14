"""Driver Wellbeing: rest after long driving stretches.

A *stretch* is time online with no real rest: online sessions joined by gaps shorter than the
break length (20 minutes) count as one. After 6 hours the driver gets no new offers; when the
current trip ends (or right away if idle) they're taken offline for a 20-minute break and can't
come back early. They're warned 30 minutes before. Taking a proper break after 4+ hours pays a
small rest bonus, once a day.
"""

from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
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


def needs_break(driver: DriverProfile, now: datetime) -> bool:
    return driving_minutes(driver, now) >= wellbeing_rules()["max_minutes"]


def status(driver: DriverProfile, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    rules = wellbeing_rules()
    minutes = driving_minutes(driver, now)
    on_break = bool(driver.break_until and driver.break_until > now)
    return {
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


def sweep(now: datetime | None = None) -> dict:
    """Every few minutes: enforce breaks for idle online drivers."""
    now = now or timezone.now()
    counts = {"warned": 0, "break": 0}
    for driver in DriverProfile.objects.filter(availability=Availability.ONLINE):
        outcome = enforce(driver, now)
        if outcome:
            counts[outcome] += 1
    return counts
