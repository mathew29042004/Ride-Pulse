"""Appeals: anyone suspended, blocked or judged in a fraud case can ask for a second look.

* One open appeal per person and subject, answered within ``APPEAL_DAYS`` (3).
* **Two-person rule:** the reviewer must not be the person who made the original decision.
* Upholding an appeal reverses the decision in the same step: the driver is reinstated, the
  rider unblocked, or the fraud case marked "not fraud". Every decision is in the audit trail.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import log_event
from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    InvalidStateTransition,
)
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify, notify_role

from .models import Appeal, AppealStatus, AppealSubject

APPEAL_DAYS = 3


def _decision_for(user, subject: str):
    """(reason, decided_by, fraud case) for the decision being appealed, or an error."""
    from apps.audit.models import AuditLog
    from apps.drivers.models import OnboardingStatus
    from apps.intelligence.models import FraudCase, FraudStatus

    if subject == AppealSubject.DRIVER_SUSPENSION:
        driver = getattr(user, "driver_profile", None)
        if driver is None or driver.onboarding_status != OnboardingStatus.SUSPENDED:
            raise BusinessRuleViolation("Your driver account isn't suspended.")
        log = (
            AuditLog.objects.filter(entity_type="drivers.driverprofile", entity_id=str(driver.pk))
            .order_by("-pk")
            .first()
        )
        return driver.suspended_reason or "Suspended", log.actor if log else None, None
    if subject == AppealSubject.RIDER_BLOCK:
        rider = getattr(user, "rider_profile", None)
        if rider is None or not rider.is_blocked:
            raise BusinessRuleViolation("Your account isn't blocked.")
        log = (
            AuditLog.objects.filter(entity_type="riders.riderprofile", entity_id=str(rider.pk))
            .order_by("-pk")
            .first()
        )
        return rider.blocked_reason or "Blocked", log.actor if log else None, None
    case = (
        FraudCase.objects.filter(status=FraudStatus.CONFIRMED)
        .filter(**({"driver__user": user} if user.is_driver else {"rider__user": user}))
        .order_by("-reviewed_at")
        .first()
    )
    if case is None:
        raise BusinessRuleViolation("There's no fraud decision on your account.")
    return f"{case.get_kind_display()}: {case.summary}", case.reviewed_by, case


@transaction.atomic
def submit(user, subject: str, *, statement: str, now: datetime | None = None) -> Appeal:
    now = now or timezone.now()
    if subject not in AppealSubject.values:
        raise BusinessRuleViolation("Unknown subject.", field="subject")
    statement = statement.strip()
    if len(statement) < 20:
        raise BusinessRuleViolation(
            "Explain what happened (at least a couple of sentences).", field="statement"
        )
    if Appeal.objects.filter(user=user, subject=subject, status=AppealStatus.OPEN).exists():
        raise ConflictError("You already have an appeal open for this.")
    reason, decided_by, case = _decision_for(user, subject)
    appeal = Appeal.objects.create(
        number=next_reference("APL", year=timezone.localtime(now).year),
        user=user,
        subject=subject,
        original_reason=reason[:255],
        original_decided_by=decided_by,
        fraud_case=case,
        statement=statement[:4000],
        due_at=now + timedelta(days=APPEAL_DAYS),
        created_at=now,
    )
    notify(
        user,
        f"Appeal {appeal.number} received",
        f"A different reviewer will decide within {APPEAL_DAYS} days.",
        link="/appeals",
    )
    notify_role(
        "ASSOC_SUPPORT",
        f"New appeal {appeal.number}",
        appeal.get_subject_display(),
        level=Level.INFO,
        link="/ops/trust?tab=appeals",
    )
    return appeal


@transaction.atomic
def decide(
    appeal: Appeal, *, reviewer, uphold: bool, note: str, now: datetime | None = None
) -> Appeal:
    from apps.drivers.services import reinstate_driver
    from apps.intelligence.models import FraudStatus
    from apps.riders.services import set_blocked

    now = now or timezone.now()
    appeal = Appeal.objects.select_for_update().get(pk=appeal.pk)
    if appeal.status != AppealStatus.OPEN:
        raise InvalidStateTransition("This appeal has been decided.")
    if appeal.original_decided_by_id and appeal.original_decided_by_id == reviewer.pk:
        raise ActionNotPermitted("Someone else must review an appeal against your own decision.")
    if len(note.strip()) < 10:
        raise BusinessRuleViolation("Explain the decision to the person.", field="note")
    if uphold:
        user = appeal.user
        if appeal.subject == AppealSubject.DRIVER_SUSPENSION:
            reinstate_driver(user.driver_profile, actor=reviewer)
        elif appeal.subject == AppealSubject.RIDER_BLOCK:
            set_blocked(user.rider_profile, False, actor=reviewer)
        elif appeal.fraud_case_id:
            case = appeal.fraud_case
            case.status, case.review_note = (
                FraudStatus.DISMISSED,
                f"Reversed on appeal {appeal.number}: {note}",
            )
            case.save(update_fields=["status", "review_note"])
            if case.driver_id and case.action_taken == "SUSPEND_DRIVER":
                reinstate_driver(case.driver, actor=reviewer)
            if case.rider_id and case.action_taken == "BLOCK_RIDER":
                set_blocked(case.rider, False, actor=reviewer)
    appeal.status = AppealStatus.UPHELD if uphold else AppealStatus.DENIED
    appeal.reviewed_by, appeal.decision_note, appeal.decided_at = reviewer, note.strip(), now
    appeal.save()
    log_event(
        AuditAction.ACTION,
        appeal,
        message=f"Appeal {appeal.status.lower()}: {note.strip()[:200]}",
        actor=reviewer,
    )
    notify(
        appeal.user,
        f"Appeal {appeal.number}: " + ("accepted" if uphold else "not accepted"),
        note.strip()[:300],
        level=Level.SUCCESS if uphold else Level.WARNING,
        email=True,
    )
    return appeal
