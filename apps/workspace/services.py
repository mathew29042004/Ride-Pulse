"""Tasks, meetings and check-ins.

Work flows down the org chart: you can give work to anyone below you (your reports, their
reports, and so on). Admins can give work to every employee. Everybody can see and update the
work given to them, and managers see everything assigned inside their part of the tree.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import (
    OPEN_TASK_STATUSES,
    AttendeeResponse,
    CommentKind,
    Meeting,
    MeetingAttendee,
    MeetingStatus,
    Priority,
    TaskComment,
    TaskStatus,
    WorkTask,
)

User = get_user_model()

TASK_LINK = "/ops/work/tasks/{pk}"
MEETING_LINK = "/ops/work/meetings/{pk}"


# --- The org chart ---------------------------------------------------------------------------


def _children() -> dict[int | None, list[tuple[int, int]]]:
    """reports_to profile id -> [(profile id, user id)] for every employee."""
    tree: dict[int | None, list[tuple[int, int]]] = {}
    for pk, user_id, parent in StaffProfile.objects.values_list("pk", "user_id", "reports_to_id"):
        tree.setdefault(parent, []).append((pk, user_id))
    return tree


def team_of(user, *, direct_only: bool = False) -> set[int]:
    """User ids of everyone below ``user`` in the org chart (admins: every employee)."""
    if user.role == Role.ADMIN and not direct_only:
        return set(StaffProfile.objects.exclude(user=user).values_list("user_id", flat=True))
    profile = StaffProfile.objects.filter(user=user).values_list("pk", flat=True).first()
    if profile is None:
        return set()
    tree, found, stack = _children(), set(), [profile]
    while stack:
        for child, user_id in tree.get(stack.pop(), []):
            found.add(user_id)
            if not direct_only:
                stack.append(child)
    return found


def direct_reports(user) -> set[int]:
    direct = team_of(user, direct_only=True)
    if user.role == Role.ADMIN:
        # Anyone at the top of the chart without a manager also reports to the admin.
        roots = StaffProfile.objects.filter(reports_to__isnull=True).exclude(user=user)
        direct |= set(roots.values_list("user_id", flat=True))
    return direct


def can_assign(manager, assignee_id: int) -> bool:
    return assignee_id in team_of(manager)


def visible_tasks(user):
    """Tasks a person may see: theirs, ones they gave out, and anything inside their team."""
    team = team_of(user)
    return WorkTask.objects.filter(
        Q(assignee=user) | Q(assigned_by=user) | Q(assignee_id__in=team)
    ).distinct()


def visible_meetings(user):
    return Meeting.objects.filter(
        Q(organizer=user) | Q(attendees__user=user) | Q(organizer_id__in=team_of(user))
    ).distinct()


# --- Tasks -----------------------------------------------------------------------------------


def _comment(task, author, body: str, kind: str = CommentKind.COMMENT, *, now=None):
    return TaskComment.objects.create(
        task=task, author=author, body=body, kind=kind, created_at=now or timezone.now()
    )


@transaction.atomic
def create_tasks(
    *,
    manager,
    title: str,
    due_at: datetime,
    assignee_ids: list[int] | None = None,
    whole_team: bool = False,
    description: str = "",
    priority: str = Priority.NORMAL,
    target: int | None = None,
    meeting: Meeting | None = None,
    now: datetime | None = None,
) -> list[WorkTask]:
    """One task per person. ``whole_team`` gives it to each of the manager's direct reports."""
    now = now or timezone.now()
    title = " ".join(title.split())[:160]
    if len(title) < 3:
        raise BusinessRuleViolation("Give the task a title.", field="title")
    if due_at <= now:
        raise BusinessRuleViolation("The deadline must be in the future.", field="due_at")
    if target is not None and target < 1:
        raise BusinessRuleViolation("The target must be at least 1.", field="target")
    people = set(assignee_ids or [])
    if whole_team:
        people |= direct_reports(manager)
    if not people:
        raise BusinessRuleViolation("Choose who should do this.", field="assignee_ids")
    team = team_of(manager)
    if not people <= team:
        raise ActionNotPermitted("You can only give work to people in your team.")
    batch = next_reference("WB", year=timezone.localtime(now).year) if len(people) > 1 else ""
    tasks = []
    for person in User.objects.filter(pk__in=people).order_by("pk"):
        task = WorkTask.objects.create(
            number=next_reference("TSK", year=timezone.localtime(now).year),
            title=title,
            description=description.strip(),
            assigned_by=manager,
            assignee=person,
            priority=priority,
            due_at=due_at,
            target=target,
            batch=batch,
            meeting=meeting,
        )
        _comment(
            task, manager, f"Assigned to {person.get_full_name()}", CommentKind.SYSTEM, now=now
        )
        notify(
            person,
            f"New task from {manager.get_full_name()}: {title}",
            f"Due {timezone.localtime(due_at):%a %d %b, %I:%M %p}"
            + (f" · target {target}" if target else ""),
            level=Level.WARNING if priority in (Priority.HIGH, Priority.URGENT) else Level.INFO,
            link=TASK_LINK.format(pk=task.pk),
        )
        tasks.append(task)
    return tasks


def _require_assignee(task: WorkTask, user) -> None:
    if task.assignee_id != user.pk:
        raise ActionNotPermitted("Only the person doing this task can update it.")


def _require_manager(task: WorkTask, user) -> None:
    if task.assigned_by_id != user.pk and task.assignee_id not in team_of(user):
        raise ActionNotPermitted("Only their managers can do this.")


@transaction.atomic
def update_task(
    task: WorkTask,
    *,
    user,
    status: str | None = None,
    progress: int | None = None,
    note: str = "",
    now: datetime | None = None,
) -> WorkTask:
    """The assignee moves the task along (start, report progress, finish)."""
    now = now or timezone.now()
    task = WorkTask.objects.select_for_update().get(pk=task.pk)
    _require_assignee(task, user)
    if not task.is_open:
        raise InvalidStateTransition("This task is already closed.")
    changes = []
    if progress is not None:
        if progress < 0 or (task.target and progress > task.target * 10):
            raise BusinessRuleViolation("That progress doesn't look right.", field="progress")
        task.progress = progress
        changes.append(f"{progress}/{task.target}" if task.target else f"progress {progress}")
        if task.target and progress >= task.target and status is None:
            status = TaskStatus.DONE
    if status is not None:
        if status not in (TaskStatus.IN_PROGRESS, TaskStatus.DONE):
            raise BusinessRuleViolation("You can start or finish a task.", field="status")
        task.status = status
        changes.append(TaskStatus(status).label.lower())
    if task.status == TaskStatus.IN_PROGRESS and task.started_at is None:
        task.started_at = now
    if task.status == TaskStatus.DONE:
        task.completed_at = now
        task.started_at = task.started_at or now
    task.save()
    body = note.strip() or ("Update: " + ", ".join(changes) if changes else "")
    if body:
        _comment(task, user, body, CommentKind.UPDATE, now=now)
    if task.status == TaskStatus.DONE:
        late = now > task.due_at
        notify(
            task.assigned_by,
            f"{user.get_full_name()} finished: {task.title}" + (" (late)" if late else ""),
            note.strip(),
            level=Level.WARNING if late else Level.SUCCESS,
            link=TASK_LINK.format(pk=task.pk),
        )
    elif note.strip():
        notify(
            task.assigned_by,
            f"Update on {task.title} from {user.get_full_name()}",
            note.strip()[:200],
            link=TASK_LINK.format(pk=task.pk),
        )
    return task


@transaction.atomic
def comment(task: WorkTask, *, user, body: str, now: datetime | None = None) -> TaskComment:
    """Guidance from a manager, or a question/answer from the assignee."""
    body = body.strip()[:2000]
    if not body:
        raise BusinessRuleViolation("Write something first.", field="body")
    is_assignee = task.assignee_id == user.pk
    if not is_assignee:
        _require_manager(task, user)
    note = _comment(task, user, body, CommentKind.COMMENT, now=now)
    other = task.assigned_by if is_assignee else task.assignee
    notify(
        other,
        f"{user.get_full_name()} on {task.title}",
        body[:200],
        link=TASK_LINK.format(pk=task.pk),
    )
    return note


@transaction.atomic
def ask_status(task: WorkTask, *, user, now: datetime | None = None) -> TaskComment:
    """ "What's the status?": the assignee is nudged to post an update."""
    _require_manager(task, user)
    if not task.is_open:
        raise InvalidStateTransition("This task is already closed.")
    note = _comment(task, user, "What's the status on this?", CommentKind.STATUS_REQUEST, now=now)
    notify(
        task.assignee,
        f"{user.get_full_name()} asked for a status update",
        task.title,
        level=Level.WARNING,
        link=TASK_LINK.format(pk=task.pk),
    )
    return note


def pending_status_requests(task: WorkTask) -> bool:
    """A status request with no update from the assignee after it."""
    last_request = task.comments.filter(kind=CommentKind.STATUS_REQUEST).last()
    if last_request is None:
        return False
    return not task.comments.filter(
        author=task.assignee, created_at__gte=last_request.created_at
    ).exists()


@transaction.atomic
def reassign_or_cancel(
    task: WorkTask,
    *,
    user,
    cancel: bool = False,
    assignee_id: int | None = None,
    due_at: datetime | None = None,
    now: datetime | None = None,
) -> WorkTask:
    """Managers can cancel, hand to someone else in their team, or move the deadline."""
    now = now or timezone.now()
    task = WorkTask.objects.select_for_update().get(pk=task.pk)
    _require_manager(task, user)
    if not task.is_open:
        raise InvalidStateTransition("This task is already closed.")
    if cancel:
        task.status = TaskStatus.CANCELLED
        task.save()
        _comment(task, user, "Cancelled", CommentKind.SYSTEM, now=now)
        notify(task.assignee, f"Task cancelled: {task.title}", link=TASK_LINK.format(pk=task.pk))
        return task
    if assignee_id and assignee_id != task.assignee_id:
        if not can_assign(user, assignee_id):
            raise ActionNotPermitted("You can only give work to people in your team.")
        old = task.assignee
        task.assignee = User.objects.get(pk=assignee_id)
        task.status, task.started_at, task.progress = TaskStatus.TODO, None, 0
        _comment(
            task,
            user,
            f"Moved from {old.get_full_name()} to {task.assignee.get_full_name()}",
            CommentKind.SYSTEM,
            now=now,
        )
        notify(
            task.assignee,
            f"New task from {user.get_full_name()}: {task.title}",
            link=TASK_LINK.format(pk=task.pk),
        )
    if due_at:
        if due_at <= now:
            raise BusinessRuleViolation("The deadline must be in the future.", field="due_at")
        task.due_at, task.overdue_flagged_at = due_at, None
        _comment(
            task,
            user,
            f"Deadline moved to {timezone.localtime(due_at):%a %d %b, %I:%M %p}",
            CommentKind.SYSTEM,
            now=now,
        )
    task.save()
    return task


def flag_overdue(*, now: datetime | None = None) -> int:
    """Tell the assignee and their manager once when a task passes its deadline."""
    now = now or timezone.now()
    overdue = WorkTask.objects.filter(
        status__in=OPEN_TASK_STATUSES, due_at__lt=now, overdue_flagged_at__isnull=True
    ).select_related("assignee", "assigned_by")
    count = 0
    for task in overdue:
        WorkTask.objects.filter(pk=task.pk).update(overdue_flagged_at=now)
        _comment(task, None, "Overdue", CommentKind.SYSTEM, now=now)
        link = TASK_LINK.format(pk=task.pk)
        notify(
            task.assignee,
            f"Overdue: {task.title}",
            "Post an update for your manager.",
            level=Level.DANGER,
            link=link,
        )
        notify(
            task.assigned_by,
            f"Overdue: {task.title}",
            f"{task.assignee.get_full_name()} hasn't finished it yet.",
            level=Level.WARNING,
            link=link,
        )
        count += 1
    return count


# --- Meetings --------------------------------------------------------------------------------


@transaction.atomic
def schedule_meeting(
    *,
    organizer,
    title: str,
    starts_at: datetime,
    attendee_ids: list[int] | None = None,
    whole_team: bool = False,
    agenda: str = "",
    duration_minutes: int = 15,
    repeats_daily: bool = False,
    series: str = "",
    now: datetime | None = None,
) -> Meeting:
    now = now or timezone.now()
    title = " ".join(title.split())[:160]
    if len(title) < 3:
        raise BusinessRuleViolation("Give the meeting a title.", field="title")
    if starts_at <= now:
        raise BusinessRuleViolation("Pick a time in the future.", field="starts_at")
    if not 5 <= duration_minutes <= 240:
        raise BusinessRuleViolation("Meetings run 5 minutes to 4 hours.", field="duration_minutes")
    people = set(attendee_ids or [])
    if whole_team:
        people |= direct_reports(organizer)
    people.discard(organizer.pk)
    if not people:
        raise BusinessRuleViolation("Invite at least one person.", field="attendee_ids")
    if not people <= team_of(organizer):
        raise ActionNotPermitted("You can invite people in your team.")
    number = next_reference("MTG", year=timezone.localtime(now).year)
    meeting = Meeting.objects.create(
        number=number,
        title=title,
        agenda=agenda.strip(),
        organizer=organizer,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        repeats_daily=repeats_daily,
        series=series or (number if repeats_daily else ""),
    )
    MeetingAttendee.objects.create(
        meeting=meeting, user=organizer, response=AttendeeResponse.ACCEPTED
    )
    for person in User.objects.filter(pk__in=people):
        MeetingAttendee.objects.create(meeting=meeting, user=person)
        notify(
            person,
            f"{organizer.get_full_name()} invited you: {title}",
            f"{timezone.localtime(starts_at):%a %d %b, %I:%M %p} · {duration_minutes} min"
            + (" · daily" if repeats_daily else ""),
            link=MEETING_LINK.format(pk=meeting.pk),
        )
    return meeting


def respond(meeting: Meeting, *, user, accept: bool) -> MeetingAttendee:
    invite = MeetingAttendee.objects.filter(meeting=meeting, user=user).first()
    if invite is None:
        raise ActionNotPermitted("You're not invited to this meeting.")
    if meeting.status != MeetingStatus.SCHEDULED:
        raise InvalidStateTransition("This meeting is over.")
    invite.response = AttendeeResponse.ACCEPTED if accept else AttendeeResponse.DECLINED
    invite.save(update_fields=["response"])
    if not accept:
        notify(
            meeting.organizer,
            f"{user.get_full_name()} can't make it: {meeting.title}",
            link=MEETING_LINK.format(pk=meeting.pk),
        )
    return invite


@transaction.atomic
def complete_meeting(
    meeting: Meeting,
    *,
    user,
    notes: str = "",
    present_ids: list[int] | None = None,
    action_items: list[dict] | None = None,
    now: datetime | None = None,
) -> tuple[Meeting, list[WorkTask]]:
    """Write up the meeting: notes, who came, and action items (each becomes a task)."""
    now = now or timezone.now()
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    if meeting.organizer_id != user.pk:
        raise ActionNotPermitted("Only the organiser can write up the meeting.")
    if meeting.status != MeetingStatus.SCHEDULED:
        raise InvalidStateTransition("This meeting is already closed.")
    meeting.status, meeting.notes = MeetingStatus.DONE, notes.strip()
    meeting.save()
    if present_ids is not None:
        present = set(present_ids) | {user.pk}
        for invite in meeting.attendees.all():
            invite.attended = invite.user_id in present
            invite.save(update_fields=["attended"])
    tasks = []
    for item in action_items or []:
        tasks += create_tasks(
            manager=user,
            title=item["title"],
            assignee_ids=[item["assignee_id"]],
            due_at=item.get("due_at") or now + timedelta(days=1),
            priority=item.get("priority", Priority.NORMAL),
            meeting=meeting,
            now=now,
        )
    for invite in meeting.attendees.exclude(user=user).select_related("user"):
        notify(
            invite.user,
            f"Notes from {meeting.title}",
            meeting.notes[:200] or f"{len(tasks)} action item(s)",
            link=MEETING_LINK.format(pk=meeting.pk),
        )
    if meeting.repeats_daily:
        _next_standup(meeting, now=now)
    return meeting, tasks


def cancel_meeting(meeting: Meeting, *, user, whole_series: bool = False) -> Meeting:
    if meeting.organizer_id != user.pk:
        raise ActionNotPermitted("Only the organiser can cancel the meeting.")
    if meeting.status != MeetingStatus.SCHEDULED:
        raise InvalidStateTransition("This meeting is already closed.")
    meeting.status = MeetingStatus.CANCELLED
    meeting.save(update_fields=["status", "updated_at"])
    if whole_series and meeting.series:
        Meeting.objects.filter(series=meeting.series).update(repeats_daily=False)
    for invite in meeting.attendees.exclude(user=user).select_related("user"):
        notify(invite.user, f"Cancelled: {meeting.title}", link=MEETING_LINK.format(pk=meeting.pk))
    return meeting


def _next_weekday(at: datetime) -> datetime:
    at += timedelta(days=1)
    while timezone.localtime(at).weekday() >= 5:
        at += timedelta(days=1)
    return at


def _next_standup(meeting: Meeting, *, now: datetime) -> Meeting | None:
    if Meeting.objects.filter(series=meeting.series, starts_at__gt=meeting.starts_at).exists():
        return None
    starts_at = _next_weekday(meeting.starts_at)
    while starts_at <= now:
        starts_at = _next_weekday(starts_at)
    attendees = list(
        meeting.attendees.exclude(user=meeting.organizer).values_list("user_id", flat=True)
    )
    team = team_of(meeting.organizer)
    attendees = [a for a in attendees if a in team]
    if not attendees:
        return None
    return schedule_meeting(
        organizer=meeting.organizer,
        title=meeting.title,
        starts_at=starts_at,
        attendee_ids=attendees,
        agenda=meeting.agenda,
        duration_minutes=meeting.duration_minutes,
        repeats_daily=True,
        series=meeting.series,
        now=now,
    )


def roll_daily_standups(*, now: datetime | None = None) -> int:
    """Make sure every daily stand-up series has its next meeting (missed ones roll forward)."""
    now = now or timezone.now()
    created = 0
    latest = {}
    for meeting in Meeting.objects.filter(repeats_daily=True).order_by("starts_at"):
        latest[meeting.series] = meeting
    for meeting in latest.values():
        if meeting.starts_at + timedelta(minutes=meeting.duration_minutes) < now:
            if meeting.status == MeetingStatus.SCHEDULED:
                Meeting.objects.filter(pk=meeting.pk).update(status=MeetingStatus.DONE)
            if _next_standup(meeting, now=now):
                created += 1
    return created
