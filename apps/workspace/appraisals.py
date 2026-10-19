"""Half-yearly appraisals: self-review, manager rating against real evidence, and a pay rise.

* An admin starts a cycle ("2026-H2"); everyone with a manager gets an appraisal.
* The employee writes a self-review and rates themselves (1–5).
* The manager sees the evidence for the six months (tasks done on time, tickets, SLA, CSAT,
  meetings, attendance: present, late, absent, leave) and gives the rating with a comment.
  Ratings far from the evidence (a 5 with absences or overdue work) need a written reason.
* Closing the cycle applies the pay rise for each rating to next month's salary.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.core.money import money

RAISE = {1: Decimal("0"), 2: Decimal("3"), 3: Decimal("6"), 4: Decimal("9"), 5: Decimal("12")}  # %
RATING_LABELS = {
    1: "Below expectations",
    2: "Partly meets",
    3: "Meets",
    4: "Exceeds",
    5: "Outstanding",
}
WINDOW = timedelta(days=182)


class AppraisalStatus(models.TextChoices):
    SELF = "SELF", "Self-review"
    MANAGER = "MANAGER", "With manager"
    DONE = "DONE", "Rated"
    CLOSED = "CLOSED", "Closed · raise applied"


class AppraisalCycle(models.Model):
    name = models.CharField(max_length=10, unique=True)
    started_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return self.name


class Appraisal(models.Model):
    cycle = models.ForeignKey(AppraisalCycle, on_delete=models.CASCADE, related_name="appraisals")
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appraisals"
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    status = models.CharField(
        max_length=7, choices=AppraisalStatus.choices, default=AppraisalStatus.SELF
    )
    self_review = models.TextField(blank=True)
    self_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    evidence = models.JSONField(default=dict)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    manager_comment = models.TextField(blank=True)
    raise_percent = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    new_gross = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        app_label = "workspace"
        constraints = [
            models.UniqueConstraint(fields=["cycle", "employee"], name="appraisal_once_per_cycle")
        ]

    def __str__(self) -> str:
        return f"{self.cycle_id}: {self.employee_id}"


def evidence_for(user, *, now=None) -> dict:
    from .attendance import Attendance, summary
    from .scorecards import scorecards

    now = now or timezone.now()
    manager = user.staff_profile.reports_to.user
    card = next(
        (
            r
            for r in scorecards(manager, days=WINDOW.days, now=now)["people"]
            if r["user_id"] == user.pk
        ),
        {},
    )
    att = summary(list(Attendance.objects.filter(user=user, day__gte=(now - WINDOW).date())))
    keep = [
        "done_tasks",
        "overdue_tasks",
        "on_time_rate",
        "tickets_resolved",
        "sla_met_rate",
        "csat_percent",
        "meeting_attendance",
        "documents_reviewed",
    ]
    return {**{k: card.get(k) for k in keep}, "attendance": att}


def _concerns(e: dict) -> list[str]:
    out = []
    if (e.get("attendance") or {}).get("absent", 0) >= 3:
        out.append(f"{e['attendance']['absent']} absences")
    if (e.get("overdue_tasks") or 0) >= 2:
        out.append(f"{e['overdue_tasks']} overdue tasks")
    if e.get("on_time_rate") is not None and e["on_time_rate"] < 60:
        out.append(f"{e['on_time_rate']}% tasks on time")
    return out


@transaction.atomic
def start(*, by, now=None) -> AppraisalCycle:
    from apps.accounts.models import Role, User
    from apps.notifications.services import notify

    now = now or timezone.now()
    local = timezone.localtime(now)
    name = f"{local.year}-H{1 if local.month <= 6 else 2}"
    if AppraisalCycle.objects.filter(name=name).exists():
        raise BusinessRuleViolation(f"The {name} cycle has already started.")
    cycle = AppraisalCycle.objects.create(name=name, started_at=now)
    staff = User.objects.filter(is_active=True, staff_profile__reports_to__isnull=False).exclude(
        role=Role.ADMIN
    )
    rows = [
        Appraisal(cycle=cycle, employee=u, manager=u.staff_profile.reports_to.user)
        for u in staff.select_related("staff_profile__reports_to__user")
    ]
    Appraisal.objects.bulk_create(rows)
    for a in rows:
        notify(
            a.employee,
            f"Appraisal {name}",
            "Write your self-review: what went well, what you'd improve.",
            link="/ops/appraisals",
        )
    return cycle


def self_review(a: Appraisal, *, user, text: str, rating: int) -> Appraisal:
    if a.employee_id != user.pk:
        raise ActionNotPermitted("This is someone else's appraisal.")
    if a.status != AppraisalStatus.SELF:
        raise InvalidStateTransition("Your self-review is already with your manager.")
    if len(text.strip()) < 30 or rating not in RAISE:
        raise BusinessRuleViolation(
            "Write a few sentences and rate yourself 1–5.", field="self_review"
        )
    a.self_review, a.self_rating, a.status = text.strip(), rating, AppraisalStatus.MANAGER
    a.evidence = evidence_for(a.employee)
    a.save(update_fields=["self_review", "self_rating", "status", "evidence"])
    from apps.notifications.services import notify

    notify(
        a.manager,
        f"{a.employee.get_full_name()}'s appraisal is ready",
        "Rate it with the evidence.",
        link="/ops/appraisals",
    )
    return a


def rate(a: Appraisal, *, manager, rating: int, comment: str) -> Appraisal:
    if a.manager_id != manager.pk:
        raise ActionNotPermitted("Only their manager rates this appraisal.")
    if a.status != AppraisalStatus.MANAGER:
        raise InvalidStateTransition(
            "Waiting for the self-review." if a.status == "SELF" else "Already rated."
        )
    if rating not in RAISE or len(comment.strip()) < 20:
        raise BusinessRuleViolation(
            "Give a rating 1–5 and a comment of a few sentences.", field="comment"
        )
    concerns = _concerns(a.evidence)
    if rating >= 4 and concerns and "because" not in comment.lower():
        raise BusinessRuleViolation(
            f"The evidence shows {', '.join(concerns)}. Explain the high rating (use 'because').",
            field="comment",
        )
    a.rating, a.manager_comment, a.status = rating, comment.strip(), AppraisalStatus.DONE
    a.raise_percent = RAISE[rating]
    a.save(update_fields=["rating", "manager_comment", "status", "raise_percent"])
    return a


@transaction.atomic
def close(cycle: AppraisalCycle, *, by, now=None) -> dict:
    """Apply the raises (next month) for rated appraisals; unrated ones get no raise."""
    from .payroll import SalaryStructure

    now = now or timezone.now()
    if cycle.closed_at:
        raise InvalidStateTransition("This cycle is closed.")
    applied = 0
    effective = (timezone.localdate(now).replace(day=28) + timedelta(days=5)).replace(day=1)
    for a in cycle.appraisals.filter(status=AppraisalStatus.DONE):
        salary = SalaryStructure.objects.filter(user=a.employee).first()
        if salary:
            salary.monthly_gross = money(salary.monthly_gross * (1 + a.raise_percent / 100))
            salary.effective_from = effective
            salary.save(update_fields=["monthly_gross", "effective_from"])
            a.new_gross = salary.monthly_gross
            applied += 1
        a.status = AppraisalStatus.CLOSED
        a.save(update_fields=["status", "new_gross"])
    cycle.closed_at = now
    cycle.save(update_fields=["closed_at"])
    return {"raises": applied, "effective": effective}


def row(a: Appraisal) -> dict:
    return {
        "id": a.pk,
        "cycle": a.cycle.name,
        "employee": a.employee.get_full_name(),
        "manager": a.manager.get_full_name(),
        "status": a.status,
        "status_label": a.get_status_display(),
        "self_review": a.self_review,
        "self_rating": a.self_rating,
        "evidence": a.evidence,
        "concerns": _concerns(a.evidence),
        "rating": a.rating,
        "rating_label": RATING_LABELS.get(a.rating or 0, ""),
        "manager_comment": a.manager_comment,
        "raise_percent": a.raise_percent,
        "new_gross": a.new_gross,
    }


def seed_demo(*, seed: int = 91, log=print) -> dict:
    """This half's cycle under way: most self-reviews in, about half rated by managers."""
    import random

    from apps.accounts.models import User
    from apps.notifications import services as notifications

    if AppraisalCycle.objects.exists():
        return {"appraisals": 0}
    rng = random.Random(seed)
    admin = User.objects.filter(role="ADMIN").first()
    with notifications.muted():
        cycle = start(by=admin)
        for a in cycle.appraisals.select_related("employee", "manager")[:400]:
            if rng.random() < 0.7:
                self_review(
                    a,
                    user=a.employee,
                    rating=rng.choice([3, 3, 4, 4, 5]),
                    text=rng.choice(
                        [
                            "Handled my queue on time most weeks and helped onboard new "
                            "colleagues in the city.",
                            "Closed every vehicle audit assigned to me and cut the document "
                            "review backlog.",
                            "Met my targets; I want to get better at escalations and at "
                            "writing clear updates.",
                        ]
                    ),
                )
                if rng.random() < 0.6:
                    rating = rng.choice([2, 3, 3, 4, 4, 5])
                    comment = "Reliable and well liked by the team, because the numbers back it up."
                    try:
                        rate(a, manager=a.manager, rating=rating, comment=comment)
                    except BusinessRuleViolation:
                        rate(
                            a,
                            manager=a.manager,
                            rating=3,
                            comment="Solid half with a few gaps to work on.",
                        )
    log(f"  appraisals: {cycle.name} started for {cycle.appraisals.count()} people")
    return {"appraisals": cycle.appraisals.count()}
