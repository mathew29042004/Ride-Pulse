"""Simulated employees: they accept meeting invites, start the work they're given, reply when
their manager asks for a status, report progress and (usually) finish on time.

Anyone who signed in to the app recently is a real person at the keyboard, so the bots leave
their work alone.
"""

import random
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import (
    OPEN_TASK_STATUSES,
    AttendeeResponse,
    MeetingAttendee,
    MeetingStatus,
    TaskStatus,
    WorkTask,
)
from .services import comment, pending_status_requests, respond, update_task

HUMAN_WINDOW = timedelta(hours=2)
START_AFTER = timedelta(minutes=1)
SLACKER_SHARE = 0.12  # some tasks are left to run late, so overdue alerts get exercised

STARTING = [
    "On it.",
    "Starting this now.",
    "Got it, will update you by end of day.",
    "Picking this up after my current call.",
]
UPDATES = [
    "Making progress, {done} done so far.",
    "{done} done. Waiting on a couple of people, following up.",
    "Halfway there ({done}).",
    "Working on it, {done} completed.",
]
FINISHED = [
    "Done.",
    "Completed, notes are in the tracker.",
    "All done. Flagging two cases for a second look.",
    "Finished ahead of time.",
]


def _humans(now: datetime) -> Q:
    return Q(last_login__gte=now - HUMAN_WINDOW)


def tick(*, now: datetime | None = None, rng: random.Random | None = None) -> dict:
    now = now or timezone.now()
    rng = rng or random.Random()
    counts = {"accepted": 0, "started": 0, "replied": 0, "progress": 0, "finished": 0}

    invites = (
        MeetingAttendee.objects.filter(
            response=AttendeeResponse.INVITED, meeting__status=MeetingStatus.SCHEDULED
        )
        .exclude(user__in=_bot_free_users(now))
        .select_related("meeting", "user")[:50]
    )
    for invite in invites:
        respond(invite.meeting, user=invite.user, accept=rng.random() < 0.9)
        counts["accepted"] += 1

    tasks = (
        WorkTask.objects.filter(status__in=OPEN_TASK_STATUSES, created_at__lte=now - START_AFTER)
        .exclude(assignee__in=_bot_free_users(now))
        .select_related("assignee", "assigned_by")[:100]
    )
    for task in tasks:
        user = task.assignee
        # A stable per-task coin decides who lets this one slip.
        slacker = random.Random(task.pk).random() < SLACKER_SHARE
        if pending_status_requests(task):
            done = f"{task.progress}/{task.target}" if task.target else "most"
            text = rng.choice(UPDATES).format(done=done)
            comment(task, user=user, body=text, now=now)
            counts["replied"] += 1
            continue
        if task.status == TaskStatus.TODO:
            if rng.random() < 0.5:
                update_task(
                    task,
                    user=user,
                    status=TaskStatus.IN_PROGRESS,
                    note=rng.choice(STARTING),
                    now=now,
                )
                counts["started"] += 1
            continue
        if slacker and now < task.due_at + timedelta(hours=2):
            continue
        share_of_time = _elapsed_share(task, now)
        if task.target:
            goal = min(task.target, max(task.progress, round(task.target * share_of_time * 1.3)))
            if goal > task.progress and rng.random() < 0.4:
                update_task(
                    task,
                    user=user,
                    progress=goal,
                    now=now,
                    note=rng.choice(FINISHED) if goal >= task.target else "",
                )
                counts["finished" if goal >= task.target else "progress"] += 1
        elif rng.random() < 0.15 + share_of_time:
            update_task(task, user=user, status=TaskStatus.DONE, note=rng.choice(FINISHED), now=now)
            counts["finished"] += 1
    return counts


def _elapsed_share(task: WorkTask, now: datetime) -> float:
    total = (task.due_at - task.created_at).total_seconds() or 1
    # Bots work faster than the clock so a demo shows movement within minutes.
    return min(1.0, 6 * (now - task.created_at).total_seconds() / total)


def _bot_free_users(now: datetime):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(_humans(now)).values("pk")
