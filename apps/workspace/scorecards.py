"""Manager dashboard: open and overdue work per person, plus each person's real output.

Output comes from the work itself, not from self-reporting: support tickets resolved, driver
documents reviewed, and how reliably tasks are finished on time and meetings attended.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.drivers.models import DriverDocument
from apps.support.models import SupportTicket

from .models import OPEN_TASK_STATUSES, MeetingAttendee, TaskStatus, WorkTask
from .services import direct_reports, team_of

User = get_user_model()


def _counts(queryset, field: str) -> dict[int, int]:
    return dict(queryset.values_list(field).annotate(n=Count("pk")).values_list(field, "n"))


def scorecards(manager, *, days: int = 7, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    since = now - timedelta(days=days)
    people = team_of(manager)
    tasks = WorkTask.objects.filter(assignee_id__in=people)
    open_ = _counts(tasks.filter(status__in=OPEN_TASK_STATUSES), "assignee_id")
    overdue = _counts(tasks.filter(status__in=OPEN_TASK_STATUSES, due_at__lt=now), "assignee_id")
    done = tasks.filter(status=TaskStatus.DONE, completed_at__gte=since)
    done_n = _counts(done, "assignee_id")
    on_time = _counts(done.filter(completed_at__lte=F("due_at")), "assignee_id")
    tickets = _counts(
        SupportTicket.objects.filter(assigned_to_id__in=people, resolved_at__gte=since),
        "assigned_to_id",
    )
    documents = _counts(
        DriverDocument.objects.filter(reviewed_by_id__in=people, reviewed_at__gte=since),
        "reviewed_by_id",
    )
    invites = MeetingAttendee.objects.filter(
        user_id__in=people, attended__isnull=False, meeting__starts_at__gte=since
    )
    meetings = dict(
        invites.values_list("user_id")
        .annotate(n=Count("pk"), came=Count("pk", filter=Q(attended=True)))
        .values_list("user_id", "came")
    )
    invited = _counts(invites, "user_id")
    profiles = (
        StaffProfile.objects.filter(user_id__in=people)
        .select_related("user", "city", "reports_to__user")
        .order_by("department", "employee_id")
    )
    direct = direct_reports(manager)
    rows = []
    for profile in profiles:
        uid = profile.user_id
        finished = done_n.get(uid, 0)
        rows.append(
            {
                "user_id": uid,
                "name": profile.user.get_full_name(),
                "title": profile.title,
                "role": profile.user.role,
                "department": profile.get_department_display(),
                "city": profile.city.name if profile.city else profile.state,
                "manager": profile.reports_to.user.get_full_name() if profile.reports_to else "",
                "direct_report": uid in direct,
                "open_tasks": open_.get(uid, 0),
                "overdue_tasks": overdue.get(uid, 0),
                "done_tasks": finished,
                "on_time_rate": round(100 * on_time.get(uid, 0) / finished) if finished else None,
                "tickets_resolved": tickets.get(uid, 0),
                "documents_reviewed": documents.get(uid, 0),
                "meeting_attendance": round(100 * meetings.get(uid, 0) / invited[uid])
                if invited.get(uid)
                else None,
            }
        )
    rows.sort(key=lambda r: (-r["overdue_tasks"], -r["open_tasks"], r["name"]))
    totals = {
        "people": len(rows),
        "open_tasks": sum(open_.values()),
        "overdue_tasks": sum(overdue.values()),
        "done_tasks": sum(done_n.values()),
        "on_time_rate": round(100 * sum(on_time.values()) / sum(done_n.values()))
        if done_n
        else None,
        "tickets_resolved": sum(tickets.values()),
        "documents_reviewed": sum(documents.values()),
    }
    by_department: dict[str, dict] = {}
    for row in rows:
        dept = by_department.setdefault(
            row["department"],
            {"department": row["department"], "people": 0, "open": 0, "overdue": 0, "done": 0},
        )
        dept["people"] += 1
        dept["open"] += row["open_tasks"]
        dept["overdue"] += row["overdue_tasks"]
        dept["done"] += row["done_tasks"]
    return {
        "days": days,
        "totals": totals,
        "departments": sorted(by_department.values(), key=lambda d: d["department"]),
        "people": rows,
    }
