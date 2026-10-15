"""Demo workspace: stand-ups and a week of tasks down the org chart, so the Work pages and the
scorecards have something to show (the staff bots in the simulator carry it on from there)."""

import random
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import Role
from apps.notifications import services as notifications

from . import services
from .models import Priority, TaskStatus, WorkTask

User = get_user_model()

TASKS_BY_ROLE = {
    Role.REGIONAL_MANAGER: [
        ("Review this week's cancellations in your state", None),
        ("Plan the festival-season driver drive", None),
        ("Share the monthly safety summary", None),
    ],
    Role.OPS_MANAGER: [
        ("Fix the supply gap near the airport at night", None),
        ("Call the 10 lowest-rated drivers", 10),
    ],
    Role.ASSOC_RIDES: [("Audit 15 long-pickup trips", 15)],
    Role.ASSOC_SUPPORT: [("Clear the refund backlog", 25)],
    Role.ASSOC_MAINTENANCE: [("Chase expiring insurance documents", 20)],
    Role.ASSOC_INTERCITY: [("Check outstation fares against competitors", None)],
    Role.ASSOC_PARCELS: [("Review lost-parcel claims", 8)],
    Role.SUPPORT_LEAD: [("Coach agents on SOS handling", None)],
    Role.SUPPORT_AGENT: [("Close 20 tickets today", 20)],
    Role.FLEET_EXECUTIVE: [
        ("Verify 20 pending driver documents", 20),
        ("Onboard 5 new drivers", 5),
    ],
}


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    local = timezone.localtime(day)
    return timezone.make_aware(datetime.combine(local.date(), time(hour, minute)))


def seed(*, seed: int = 7, log=print, now: datetime | None = None) -> dict:
    if WorkTask.objects.exists():
        return {"work_tasks": 0}
    now = now or timezone.now()
    rng = random.Random(seed)
    admin = User.objects.filter(role=Role.ADMIN, staff_profile__isnull=False).first()
    if admin is None:
        return {"work_tasks": 0}
    log("Giving the team a week of tasks and stand-ups…")
    made = meetings = 0
    with notifications.muted():
        # Managers from the top down, each handing work to their direct reports.
        managers = [admin, *User.objects.filter(staff_profile__reports__isnull=False).distinct()]
        for manager in managers:
            reports = list(services.direct_reports(manager))
            if not reports:
                continue
            meetings += _standup(manager, reports, now)
            for person in User.objects.filter(pk__in=rng.sample(reports, min(len(reports), 6))):
                options = TASKS_BY_ROLE.get(person.role) or [("Send me a weekly update", None)]
                for days_ago in (6, 3, 0):
                    title, target = rng.choice(options)
                    created = now - timedelta(days=days_ago)
                    made += _task(manager, person, title, target, created, rng, now)
    log(f"  {made} tasks, {meetings} stand-ups")
    return {"work_tasks": made, "work_meetings": meetings}


def _standup(manager, reports: list[int], now: datetime) -> int:
    start = _at(now, 9, 30)
    while start <= now or timezone.localtime(start).weekday() >= 5:
        start += timedelta(days=1)
    services.schedule_meeting(
        organizer=manager,
        title="Daily stand-up",
        agenda="1. Yesterday's numbers\n2. Today's priorities\n3. Blockers",
        starts_at=start,
        attendee_ids=reports[:12],
        repeats_daily=True,
        now=now,
    )
    return 1


def _task(manager, person, title, target, created, rng: random.Random, now: datetime) -> int:
    due = created + timedelta(hours=rng.choice([8, 24, 48]))
    if due <= now and created > now - timedelta(hours=1):
        due = now + timedelta(hours=8)
    (task,) = services.create_tasks(
        manager=manager,
        title=title,
        assignee_ids=[person.pk],
        target=target,
        priority=rng.choice([Priority.NORMAL, Priority.NORMAL, Priority.HIGH, Priority.URGENT]),
        due_at=due,
        now=created,
    )
    WorkTask.objects.filter(pk=task.pk).update(created_at=created)
    if created < now - timedelta(days=1):
        # Older work: mostly finished (some late, a few still open and overdue).
        roll = rng.random()
        if roll < 0.75:
            finished = due - timedelta(hours=rng.uniform(1, 6))
        elif roll < 0.9:
            finished = due + timedelta(hours=rng.uniform(1, 12))
        else:
            return 1
        WorkTask.objects.filter(pk=task.pk).update(
            status=TaskStatus.DONE,
            progress=target or 0,
            started_at=created + timedelta(hours=1),
            completed_at=min(finished, now),
        )
    return 1
