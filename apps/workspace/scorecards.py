"""Manager dashboard: open and overdue work per person, plus each person's real output.

Output comes from the work itself, not from self-reporting: support tickets resolved, driver
documents reviewed, and how reliably tasks are finished on time and meetings attended.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Min, OuterRef, Q, Subquery
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.drivers.models import DriverDocument
from apps.support.models import SupportTicket, TicketMessage

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
    response = _first_response_minutes(people, since)
    sla = dict(
        SupportTicket.objects.filter(assigned_to_id__in=people, resolved_at__gte=since)
        .values_list("assigned_to_id")
        .annotate(met=Count("pk", filter=Q(resolved_at__lte=F("sla_due_at"))))
        .values_list("assigned_to_id", "met")
    )
    review_hours = dict(
        DriverDocument.objects.filter(reviewed_by_id__in=people, reviewed_at__gte=since)
        .values_list("reviewed_by_id")
        .annotate(t=Avg(F("reviewed_at") - F("created_at")))
        .values_list("reviewed_by_id", "t")
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
                "avg_response_minutes": response.get(uid),
                "sla_met_rate": round(100 * sla.get(uid, 0) / tickets[uid])
                if tickets.get(uid)
                else None,
                "avg_review_hours": round(review_hours[uid].total_seconds() / 3600, 1)
                if review_hours.get(uid)
                else None,
            }
        )
        rows[-1]["needs_guidance"] = _needs_guidance(rows[-1])
    rows.sort(
        key=lambda r: (not r["needs_guidance"], -r["overdue_tasks"], -r["open_tasks"], r["name"])
    )
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
        "needs_guidance": sum(r["needs_guidance"] for r in rows),
        "avg_response_minutes": round(sum(response.values()) / len(response)) if response else None,
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


# Someone "needs guidance" when their work is slipping on any of these measures.
GUIDANCE_RULES = {
    "overdue_tasks": lambda r: r["overdue_tasks"] >= 2,
    # Rates only count once there's enough work to judge (3+ tasks or tickets).
    "on_time_rate": lambda r: r["done_tasks"] >= 3 and r["on_time_rate"] < 60,
    "sla_met_rate": lambda r: r["tickets_resolved"] >= 3 and r["sla_met_rate"] < 70,
    "avg_response_minutes": lambda r: (r["avg_response_minutes"] or 0) > 120,
}


def _needs_guidance(row: dict) -> bool:
    return any(rule(row) for rule in GUIDANCE_RULES.values())


def _first_response_minutes(people: set[int], since: datetime) -> dict[int, int]:
    """Average minutes from a ticket being opened to its agent's first reply, per agent."""
    first_reply = (
        TicketMessage.objects.filter(ticket=OuterRef("pk"), author=OuterRef("assigned_to"))
        .order_by()
        .values("ticket")
        .annotate(at=Min("created_at"))
        .values("at")
    )
    rows = (
        SupportTicket.objects.filter(assigned_to_id__in=people, created_at__gte=since)
        .annotate(replied=Subquery(first_reply))
        .filter(replied__isnull=False)
        .values_list("assigned_to_id")
        .annotate(t=Avg(F("replied") - F("created_at")))
        .values_list("assigned_to_id", "t")
    )
    return {uid: round(t.total_seconds() / 60) for uid, t in rows if t is not None}
