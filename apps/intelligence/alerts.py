"""Alerts that create tasks: every few minutes each city's last hour is checked against simple
rules. When one trips, an alert is opened and a task lands with the manager who owns that
problem (the city operations manager, the state's rides or support lead, or the regional
manager), assigned by their own manager. When the numbers recover, the alert closes itself.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.geo.models import City
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.reliability.jobs import tracked
from apps.rides.models import Trip, TripStatus
from apps.support.models import SafetyIncident, SupportTicket, TicketStatus
from apps.workspace import services as work
from apps.workspace.models import Priority

from .models import AlertKind, AlertStatus, OpsAlert

User = get_user_model()

WINDOW = timedelta(hours=1)
MIN_REQUESTS = 15  # too few trips to judge a rate
CANCEL_RATE = 0.35
NO_DRIVER_RATE = 0.20
SOS_COUNT = 3
BACKLOG = 5

# Who owns which problem: the first role found in the city, then the state, wins.
OWNERS = {
    AlertKind.HIGH_CANCELLATIONS: (Role.OPS_MANAGER, Role.ASSOC_RIDES, Role.REGIONAL_MANAGER),
    AlertKind.LOW_SUPPLY: (Role.OPS_MANAGER, Role.ASSOC_MAINTENANCE, Role.REGIONAL_MANAGER),
    AlertKind.SOS_SPIKE: (Role.ASSOC_RIDES, Role.OPS_MANAGER, Role.REGIONAL_MANAGER),
    AlertKind.SUPPORT_BACKLOG: (Role.SUPPORT_LEAD, Role.ASSOC_SUPPORT, Role.REGIONAL_MANAGER),
}

PLAYBOOK = {
    AlertKind.HIGH_CANCELLATIONS: (
        "Find out why trips are being cancelled: check pickup ETAs, surge and driver "
        "cancellations, and fix the worst zones."
    ),
    AlertKind.LOW_SUPPLY: (
        "Riders are going without drivers. Nudge offline drivers, check incentives and move "
        "supply towards the busy zones."
    ),
    AlertKind.SOS_SPIKE: (
        "Several SOS alerts in an hour. Make sure each one is handled, look for a common "
        "driver or area, and report back."
    ),
    AlertKind.SUPPORT_BACKLOG: (
        "Tickets are past their SLA. Reassign agents, clear the oldest first, and tell me "
        "what caused the backlog."
    ),
}


@dataclass
class Finding:
    kind: str
    severity: str
    title: str
    detail: str
    metrics: dict


BASELINE = timedelta(days=7)
SPIKE = 0.15  # a rate must also be this far above the city's own normal level


def _baseline_rates(now: datetime) -> dict[int, dict]:
    """Each city's normal cancellation and no-driver rates over the past week."""
    rows = (
        Trip.objects.filter(requested_at__gte=now - BASELINE, requested_at__lt=now - WINDOW)
        .values("city_id")
        .annotate(
            requests=Count("pk"),
            cancelled=Count("pk", filter=Q(status=TripStatus.CANCELLED)),
            no_driver=Count("pk", filter=Q(status=TripStatus.NO_DRIVER_FOUND)),
        )
    )
    return {
        r["city_id"]: {
            "cancel_rate": r["cancelled"] / r["requests"],
            "no_driver_rate": r["no_driver"] / r["requests"],
        }
        for r in rows
        if r["requests"] >= 50
    }


def _city_metrics(now: datetime) -> dict[int, dict]:
    since = now - WINDOW
    trips = (
        Trip.objects.filter(requested_at__gte=since, requested_at__lt=now)
        .values("city_id")
        .annotate(
            requests=Count("pk"),
            cancelled=Count("pk", filter=Q(status=TripStatus.CANCELLED)),
            no_driver=Count("pk", filter=Q(status=TripStatus.NO_DRIVER_FOUND)),
        )
    )
    metrics: dict[int, dict] = {row["city_id"]: dict(row) for row in trips}
    for row in (
        SafetyIncident.objects.filter(created_at__gte=since)
        .values("trip__city_id")
        .annotate(n=Count("pk"))
    ):
        metrics.setdefault(row["trip__city_id"], {})["sos"] = row["n"]
    for row in (
        SupportTicket.objects.filter(
            sla_due_at__lt=now,
            trip__isnull=False,
            status__in=[TicketStatus.OPEN, TicketStatus.IN_PROGRESS],
        )
        .values("trip__city_id")
        .annotate(n=Count("pk"))
    ):
        metrics.setdefault(row["trip__city_id"], {})["backlog"] = row["n"]
    for city_id, normal in _baseline_rates(now).items():
        metrics.setdefault(city_id, {}).update(normal)
    return metrics


def findings_for(city: City, m: dict) -> list[Finding]:
    found = []
    requests = m.get("requests", 0)
    if requests >= MIN_REQUESTS:
        rate = m.get("cancelled", 0) / requests
        normal = m.get("cancel_rate", 0)
        if rate >= max(CANCEL_RATE, normal + SPIKE):
            found.append(
                Finding(
                    AlertKind.HIGH_CANCELLATIONS,
                    "CRITICAL" if rate >= 0.5 else "WARNING",
                    f"{city.name}: {rate:.0%} of trips cancelled in the last hour",
                    f"{m['cancelled']} of {requests} requests were cancelled "
                    f"(normally {normal:.0%}).",
                    {
                        "requests": requests,
                        "cancelled": m["cancelled"],
                        "rate": round(rate, 3),
                        "normal": round(normal, 3),
                    },
                )
            )
        rate = m.get("no_driver", 0) / requests
        normal = m.get("no_driver_rate", 0)
        if rate >= max(NO_DRIVER_RATE, normal + SPIKE):
            found.append(
                Finding(
                    AlertKind.LOW_SUPPLY,
                    "CRITICAL" if rate >= 0.35 else "WARNING",
                    f"{city.name}: {rate:.0%} of riders found no driver",
                    f"{m['no_driver']} of {requests} requests ended with no driver found "
                    f"(normally {normal:.0%}).",
                    {
                        "requests": requests,
                        "no_driver": m["no_driver"],
                        "rate": round(rate, 3),
                        "normal": round(normal, 3),
                    },
                )
            )
    if m.get("sos", 0) >= SOS_COUNT:
        found.append(
            Finding(
                AlertKind.SOS_SPIKE,
                "CRITICAL",
                f"{city.name}: {m['sos']} SOS alerts in the last hour",
                "Several riders or drivers pressed SOS within an hour.",
                {"sos": m["sos"]},
            )
        )
    if m.get("backlog", 0) >= BACKLOG:
        found.append(
            Finding(
                AlertKind.SUPPORT_BACKLOG,
                "WARNING",
                f"{city.name}: {m['backlog']} support tickets past SLA",
                "Tickets from this city are waiting longer than promised.",
                {"backlog": m["backlog"]},
            )
        )
    return found


def owner_for(kind: str, city: City):
    staff = StaffProfile.objects.select_related("user", "reports_to__user").filter(
        user__is_active=True
    )
    for role in OWNERS[kind]:
        profile = (
            staff.filter(user__role=role, city=city).first()
            or staff.filter(user__role=role, state=city.state).first()
        )
        if profile:
            return profile
    return None


def _assigner(profile: StaffProfile | None):
    """The owner's own manager gives the task (an admin if they have none)."""
    if profile and profile.reports_to:
        return profile.reports_to.user
    return User.objects.filter(role=Role.ADMIN, is_active=True).order_by("pk").first()


@transaction.atomic
def _raise(city: City, finding: Finding, now: datetime) -> OpsAlert | None:
    if OpsAlert.objects.filter(kind=finding.kind, city=city, status=AlertStatus.OPEN).exists():
        return None
    profile = owner_for(finding.kind, city)
    owner = profile.user if profile else None
    alert = OpsAlert.objects.create(
        kind=finding.kind,
        city=city,
        severity=finding.severity,
        title=finding.title,
        detail=finding.detail,
        metrics=finding.metrics,
        owner=owner,
        created_at=now,
    )
    boss = _assigner(profile)
    if owner and boss and work.can_assign(boss, owner.pk):
        (task,) = work.create_tasks(
            manager=boss,
            title=f"[Alert] {finding.title}"[:160],
            description=f"{finding.detail}\n\n{PLAYBOOK[finding.kind]}\n\n(Raised automatically.)",
            assignee_ids=[owner.pk],
            priority=Priority.URGENT if finding.severity == "CRITICAL" else Priority.HIGH,
            due_at=now + timedelta(hours=2 if finding.severity == "CRITICAL" else 6),
            now=now,
        )
        OpsAlert.objects.filter(pk=alert.pk).update(task=task)
        alert.task = task
    elif boss:
        notify(boss, f"⚠️ {finding.title}", finding.detail, level=Level.WARNING, link="/ops/alerts")
    return alert


@tracked("ops-alerts", every=timedelta(minutes=5))
def check(*, now: datetime | None = None) -> dict:
    """Run every rule for every city; open new alerts and close recovered ones."""
    now = now or timezone.now()
    metrics = _city_metrics(now)
    cities = {c.pk: c for c in City.objects.filter(is_active=True)}
    opened, firing = [], set()
    for city_id, m in metrics.items():
        city = cities.get(city_id)
        if city is None:
            continue
        for finding in findings_for(city, m):
            firing.add((finding.kind, city_id))
            alert = _raise(city, finding, now)
            if alert:
                opened.append(alert.title)
    resolved = 0
    for alert in OpsAlert.objects.filter(status=AlertStatus.OPEN):
        # Give a fresh alert a little time before calling it recovered.
        if (alert.kind, alert.city_id) not in firing and now - alert.created_at >= WINDOW / 2:
            alert.status, alert.resolved_at = AlertStatus.RESOLVED, now
            alert.save(update_fields=["status", "resolved_at"])
            resolved += 1
    return {"opened": opened, "resolved": resolved}
