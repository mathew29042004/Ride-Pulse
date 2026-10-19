"""Joiners, leavers and quarterly access reviews: nobody keeps access they shouldn't have.

* **Leavers**: offboarding switches the account off and signs it out everywhere at once (every
  refresh token is revoked), hands their open tasks to their manager, puts their open support
  tickets back in the queue, removes future shifts and two-step sign-in, and records each step.
  Their final salary still runs through payroll.
* **Access reviews** (every quarter): each manager confirms every direct report's role: keep it,
  change it, or remove the person. Accounts with no sign-in for 45 days are flagged. Decisions apply
  immediately and are written to the audit log; reviews not done in 14 days are chased.
* **Joiners**: a checklist for anyone who joined in the last 30 days (manager set, salary set,
  first sign-in, two-step sign-in where the role needs it).
"""

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition

DORMANT_AFTER = timedelta(days=45)
REVIEW_WINDOW = timedelta(days=14)
STAFF_ROLES = [
    "REGIONAL_MANAGER",
    "OPS_MANAGER",
    "ASSOC_RIDES",
    "ASSOC_SUPPORT",
    "ASSOC_MAINTENANCE",
    "ASSOC_INTERCITY",
    "ASSOC_PARCELS",
    "SUPPORT_LEAD",
    "SUPPORT_AGENT",
    "FLEET_EXECUTIVE",
]


class Offboarding(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offboarding"
    )
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=200)
    last_day = models.DateField()
    steps = models.JSONField(default=list)  # [[step, detail]]
    done_at = models.DateTimeField()

    class Meta:
        app_label = "workspace"
        ordering = ["-done_at"]

    def __str__(self) -> str:
        return f"Offboarded {self.user_id}"


class AccessReview(models.Model):
    name = models.CharField(max_length=20, unique=True)  # "2026-Q4"
    started_at = models.DateTimeField()
    due_on = models.DateField()
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        app_label = "workspace"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return self.name


class Decision(models.TextChoices):
    PENDING = "PENDING", "To review"
    KEEP = "KEEP", "Keep"
    CHANGE = "CHANGE", "Change role"
    REMOVE = "REMOVE", "Remove access"


class AccessReviewItem(models.Model):
    review = models.ForeignKey(AccessReview, on_delete=models.CASCADE, related_name="items")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    role = models.CharField(max_length=20)
    capabilities = models.PositiveSmallIntegerField()
    last_login = models.DateTimeField(null=True, blank=True)
    dormant = models.BooleanField(default=False)
    decision = models.CharField(max_length=7, choices=Decision.choices, default=Decision.PENDING)
    new_role = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=200, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "workspace"
        constraints = [
            models.UniqueConstraint(fields=["review", "subject"], name="review_once_per_person")
        ]

    def __str__(self) -> str:
        return f"{self.review_id}: {self.subject_id}"


# --- Leavers ---------------------------------------------------------------------------------


@transaction.atomic
def offboard(user, *, by, reason: str, last_day=None, now=None) -> Offboarding:
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    from apps.accounts.models import Role, User
    from apps.accounts.two_factor import TwoFactor
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event
    from apps.support.models import OPEN_TICKET_STATUSES, SupportTicket

    from .models import OPEN_TASK_STATUSES, Shift, WorkTask

    now = now or timezone.now()
    if user.pk == by.pk:
        raise ActionNotPermitted("You can't offboard yourself.")
    if user.role in (Role.RIDER, Role.DRIVER):
        raise BusinessRuleViolation("Offboarding is for staff accounts.")
    if not user.is_active or hasattr(user, "offboarding"):
        raise InvalidStateTransition("Already offboarded.")
    if (
        user.role == Role.ADMIN
        and User.objects.filter(role=Role.ADMIN, is_active=True).count() <= 1
    ):
        raise BusinessRuleViolation("This is the last administrator.")
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation(
            "Say why they're leaving (resigned, contract ended…).", field="reason"
        )
    profile = getattr(user, "staff_profile", None)
    manager = profile.reports_to.user if profile and profile.reports_to_id else None
    steps = []

    User.objects.filter(pk=user.pk).update(is_active=False)
    steps.append(["Account switched off", "can't sign in"])
    tokens = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=t) for t in tokens], ignore_conflicts=True
    )
    steps.append(["Signed out everywhere", f"{len(tokens)} sessions revoked"])
    tasks = WorkTask.objects.filter(assignee=user, status__in=OPEN_TASK_STATUSES)
    moved = tasks.update(assignee=manager) if manager else 0
    steps.append(
        [
            "Open tasks handed over",
            f"{moved} to {manager.get_full_name()}" if manager else "no manager",
        ]
    )
    freed = SupportTicket.objects.filter(assigned_to=user, status__in=OPEN_TICKET_STATUSES).update(
        assigned_to=None
    )
    steps.append(["Support tickets back in the queue", str(freed)])
    shifts, _ = Shift.objects.filter(user=user, starts_at__gt=now).delete()
    steps.append(["Future shifts removed", str(shifts)])
    TwoFactor.objects.filter(user=user).delete()
    steps.append(["Two-step sign-in removed", ""])
    record = Offboarding.objects.create(
        user=user,
        by=by,
        reason=reason.strip()[:200],
        last_day=last_day or timezone.localdate(now),
        steps=steps,
        done_at=now,
    )
    log_event(AuditAction.ACTION, user, message=f"Offboarded: {record.reason}", actor=by)
    if manager:
        from apps.notifications.services import notify

        notify(
            manager,
            f"{user.get_full_name()} has been offboarded",
            f"{moved} open tasks are now yours.",
            link="/ops/work",
        )
    return record


# --- Access reviews ---------------------------------------------------------------------------


def _reviewer_for(user):
    from apps.accounts.models import Role, User

    profile = getattr(user, "staff_profile", None)
    if profile and profile.reports_to_id and profile.reports_to.user.is_active:
        return profile.reports_to.user
    return User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=user.pk).first()


@transaction.atomic
def start_review(*, by, now=None) -> AccessReview:
    from apps.accounts.models import Role, User
    from apps.accounts.roles import capabilities_for
    from apps.notifications.services import notify

    now = now or timezone.now()
    local = timezone.localtime(now)
    name = f"{local.year}-Q{(local.month - 1) // 3 + 1}"
    if AccessReview.objects.filter(name=name).exists():
        raise BusinessRuleViolation(f"The {name} review has already been started.")
    review = AccessReview.objects.create(
        name=name, started_at=now, due_on=(now + REVIEW_WINDOW).date(), started_by=by
    )
    staff = (
        User.objects.filter(is_active=True, staff_profile__isnull=False)
        .exclude(role=Role.ADMIN)
        .select_related("staff_profile__reports_to__user")
    )
    items, reviewers = [], set()
    for user in staff:
        reviewer = _reviewer_for(user)
        if reviewer is None:
            continue
        items.append(
            AccessReviewItem(
                review=review,
                reviewer=reviewer,
                subject=user,
                role=user.role,
                capabilities=len(capabilities_for(user.role)),
                last_login=user.last_login,
                dormant=user.last_login is None or now - user.last_login > DORMANT_AFTER,
            )
        )
        reviewers.add(reviewer)
    AccessReviewItem.objects.bulk_create(items)
    for reviewer in reviewers:
        count = sum(1 for i in items if i.reviewer_id == reviewer.pk)
        notify(
            reviewer,
            f"Access review {name}",
            f"Confirm the access of {count} people in your team by {review.due_on:%d %b}.",
            link="/ops/access",
        )
    return review


def decide(
    item: AccessReviewItem, *, reviewer, decision: str, new_role: str = "", note: str = "", now=None
):
    from apps.accounts.models import User
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    now = now or timezone.now()
    is_admin = reviewer.role == "ADMIN"
    if item.subject_id == reviewer.pk:
        raise ActionNotPermitted("You can't review your own access.")
    if item.reviewer_id != reviewer.pk and not is_admin:
        raise ActionNotPermitted("This person is reviewed by someone else.")
    if item.decision != Decision.PENDING:
        raise InvalidStateTransition("Already decided.")
    if decision not in (Decision.KEEP, Decision.CHANGE, Decision.REMOVE):
        raise BusinessRuleViolation("Choose keep, change or remove.", field="decision")
    if decision == Decision.CHANGE:
        if new_role not in STAFF_ROLES or new_role == item.role:
            raise BusinessRuleViolation("Choose the new role.", field="new_role")
        User.objects.filter(pk=item.subject_id).update(role=new_role)
        log_event(
            AuditAction.UPDATE,
            item.subject,
            message=f"Access review {item.review.name}: role changed",
            changes={"role": [item.role, new_role]},
            actor=reviewer,
        )
    if decision == Decision.REMOVE:
        if len(note.strip()) < 5:
            raise BusinessRuleViolation("Say why their access should be removed.", field="note")
        offboard(
            item.subject,
            by=reviewer,
            reason=f"Access review {item.review.name}: {note.strip()}",
            now=now,
        )
    item.decision, item.new_role, item.note, item.decided_at = (
        decision,
        new_role,
        note.strip()[:200],
        now,
    )
    item.save(update_fields=["decision", "new_role", "note", "decided_at"])
    return item


def chase(*, now=None) -> int:
    """Daily: remind reviewers with overdue items."""
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    now = now or timezone.now()
    late = AccessReviewItem.objects.filter(
        decision=Decision.PENDING, review__due_on__lt=timezone.localdate(now)
    )
    reviewers = {}
    for item in late.select_related("reviewer", "review"):
        reviewers.setdefault(item.reviewer, []).append(item)
    for reviewer, items in reviewers.items():
        notify(
            reviewer,
            f"Access review {items[0].review.name} is overdue",
            f"{len(items)} people still to review.",
            level=Level.WARNING,
            link="/ops/access",
        )
    return len(reviewers)


def item_row(i: AccessReviewItem) -> dict:
    return {
        "id": i.pk,
        "review": i.review.name,
        "subject_id": i.subject_id,
        "name": i.subject.get_full_name(),
        "title": getattr(getattr(i.subject, "staff_profile", None), "title", ""),
        "role": i.role,
        "capabilities": i.capabilities,
        "last_login": i.last_login,
        "dormant": i.dormant,
        "reviewer": i.reviewer.get_full_name(),
        "decision": i.decision,
        "decision_label": i.get_decision_display(),
        "new_role": i.new_role,
        "note": i.note,
    }


def review_progress(review: AccessReview) -> dict:
    items = review.items.all()
    total = items.count()
    done = items.exclude(decision=Decision.PENDING).count()
    counts = {d: items.filter(decision=d).count() for d in Decision.values}
    return {
        "name": review.name,
        "due_on": review.due_on,
        "total": total,
        "done": done,
        "pct": round(100 * done / total) if total else 100,
        "decisions": counts,
        "dormant": items.filter(dormant=True).count(),
    }


# --- Joiners ----------------------------------------------------------------------------------


def joiners(*, now=None) -> list[dict]:
    from apps.accounts.models import StaffProfile
    from apps.accounts.two_factor import status as two_factor_status

    now = now or timezone.now()
    since = timezone.localdate(now) - timedelta(days=30)
    rows = []
    for p in StaffProfile.objects.filter(joined_on__gte=since, user__is_active=True).select_related(
        "user", "reports_to__user"
    ):
        tf = two_factor_status(p.user)
        checks = {
            "Manager set": bool(p.reports_to_id),
            "Salary set": hasattr(p.user, "salary"),
            "Signed in": p.user.last_login is not None,
            "Two-step sign-in": tf["enabled"] or not tf["required"],
        }
        rows.append(
            {
                "user_id": p.user_id,
                "name": p.user.get_full_name(),
                "title": p.title,
                "joined_on": p.joined_on,
                "checks": checks,
                "done": all(checks.values()),
            }
        )
    return rows
