"""The morning briefing: yesterday in numbers for leadership, every day at 8 am.

Trips and money, the best and worst cities, safety and support, new drivers, open alerts and
fraud cases, and how the team did on its tasks.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.drivers.models import DriverProfile, OnboardingStatus
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.rides.models import Trip, TripStatus
from apps.support.models import SafetyIncident, SupportTicket
from apps.workspace.models import OPEN_TASK_STATUSES, TaskStatus, WorkTask

from .models import AlertStatus, DailyBriefing, FraudCase, FraudStatus, OpsAlert

User = get_user_model()
READERS = (Role.ADMIN, Role.REGIONAL_MANAGER)


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def _money(value) -> str:
    return str((value or Decimal(0)).quantize(Decimal("0.01")))


def _trip_numbers(start: datetime, end: datetime) -> dict:
    trips = Trip.objects.filter(requested_at__gte=start, requested_at__lt=end)
    agg = trips.aggregate(
        requests=Count("pk"),
        completed=Count("pk", filter=Q(status=TripStatus.COMPLETED)),
        cancelled=Count("pk", filter=Q(status=TripStatus.CANCELLED)),
        no_driver=Count("pk", filter=Q(status=TripStatus.NO_DRIVER_FOUND)),
        gmv=Sum("fare_total", filter=Q(status=TripStatus.COMPLETED)),
        commission=Sum("platform_commission", filter=Q(status=TripStatus.COMPLETED)),
    )
    agg["completion_rate"] = (
        round(100 * agg["completed"] / agg["requests"], 1) if agg["requests"] else None
    )
    agg["gmv"], agg["commission"] = _money(agg["gmv"]), _money(agg["commission"])
    return agg


def build(day: date) -> dict:
    start, end = _bounds(day)
    today = _trip_numbers(start, end)
    week_ago = _trip_numbers(start - timedelta(days=7), end - timedelta(days=7))
    by_city = list(
        Trip.objects.filter(requested_at__gte=start, requested_at__lt=end)
        .values("city__name")
        .annotate(
            requests=Count("pk"),
            completed=Count("pk", filter=Q(status=TripStatus.COMPLETED)),
            gmv=Sum("fare_total", filter=Q(status=TripStatus.COMPLETED)),
        )
        .filter(requests__gte=10)
    )
    for row in by_city:
        row["completion_rate"] = round(100 * row["completed"] / row["requests"], 1)
        row["gmv"] = _money(row["gmv"])
        row["city"] = row.pop("city__name")
    by_city.sort(key=lambda r: r["completion_rate"])
    tickets = SupportTicket.objects.filter(created_at__gte=start, created_at__lt=end)
    resolved = SupportTicket.objects.filter(resolved_at__gte=start, resolved_at__lt=end)
    tasks_done = WorkTask.objects.filter(
        status=TaskStatus.DONE, completed_at__gte=start, completed_at__lt=end
    )
    done_n = tasks_done.count()
    late = tasks_done.filter(completed_at__gt=F("due_at")).count()
    return {
        "day": day.isoformat(),
        "trips": today,
        "week_ago": week_ago,
        "worst_cities": by_city[:3],
        "best_cities": list(reversed(by_city[-3:])),
        "safety": {
            "sos": SafetyIncident.objects.filter(created_at__gte=start, created_at__lt=end).count(),
            "ambulance": SafetyIncident.objects.filter(
                created_at__gte=start, created_at__lt=end, ambulance_requested=True
            ).count(),
        },
        "support": {
            "opened": tickets.count(),
            "resolved": resolved.count(),
            "resolved_in_sla": resolved.filter(resolved_at__lte=F("sla_due_at")).count(),
            "open_past_sla": SupportTicket.objects.filter(
                sla_due_at__lt=end, resolved_at__isnull=True
            )
            .exclude(status__in=["RESOLVED", "CLOSED"])
            .count(),
        },
        "drivers": {
            "approved": DriverProfile.objects.filter(
                approved_at__gte=start, approved_at__lt=end
            ).count(),
            "total_approved": DriverProfile.objects.filter(
                onboarding_status=OnboardingStatus.APPROVED
            ).count(),
        },
        "alerts": {
            "raised": OpsAlert.objects.filter(created_at__gte=start, created_at__lt=end).count(),
            "open": [
                {"title": a.title, "severity": a.severity}
                for a in OpsAlert.objects.filter(status=AlertStatus.OPEN)[:5]
            ],
        },
        "fraud": {
            "open_cases": FraudCase.objects.filter(status=FraudStatus.OPEN).count(),
            "new": FraudCase.objects.filter(created_at__gte=start, created_at__lt=end).count(),
        },
        "team": {
            "tasks_done": done_n,
            "tasks_late": late,
            "tasks_overdue": WorkTask.objects.filter(
                status__in=OPEN_TASK_STATUSES, due_at__lt=end
            ).count(),
        },
        "headline": _headline(today, week_ago),
    }


def rupees(amount) -> str:
    """Indian digit grouping: ₹3,97,133."""
    whole = str(round(Decimal(amount)))
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join([g for g in [head, *groups] if g] + [tail])


def _headline(today: dict, week_ago: dict) -> str:
    if not today["requests"]:
        return "A quiet day: no trips were requested."
    parts = [f"{today['completed']} trips completed out of {today['requests']} requests"]
    if week_ago["completed"]:
        change = 100 * (today["completed"] - week_ago["completed"]) / week_ago["completed"]
        parts.append(f"{change:+.0f}% on the same day last week")
    parts.append(f"{rupees(today['gmv'])} in bookings")
    return ", ".join(parts) + "."


def generate(*, day: date | None = None, now: datetime | None = None, send: bool = True):
    """Write (or rewrite) the briefing for ``day`` (default: yesterday) and tell leadership."""
    now = now or timezone.now()
    day = day or (timezone.localdate(now) - timedelta(days=1))
    briefing, _ = DailyBriefing.objects.update_or_create(
        day=day, defaults={"data": build(day), "created_at": now}
    )
    if send:
        headline = briefing.data["headline"]
        for user in User.objects.filter(role__in=READERS, is_active=True):
            notify(
                user,
                f"Your morning briefing for {day:%a %d %b}",
                headline,
                level=Level.INFO,
                link=f"/ops/briefing?day={day.isoformat()}",
            )
    return briefing
