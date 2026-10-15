"""Insurance claims: every ride carries accident cover for the rider and the driver (Indian ride
apps bundle this with partner insurers). A claim is filed in the app with photos, reviewed by the
claims desk, and the approved amount is paid straight into the claimant's wallet.

* Only the trip's rider or driver can claim, during the trip or within 7 days of it ending.
* Amounts are capped by kind (``COVER``: ₹2 lakh accident, ₹1 lakh injury, ₹10,000 belongings).
* Payouts are funded by the insurer (``external:insurer`` in the ledger), never by the driver.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import ClaimDocument, ClaimKind, ClaimStatus, InsuranceClaim

CLAIM_WINDOW = timedelta(days=7)
COVER = {
    ClaimKind.ACCIDENT: Decimal("200000"),
    ClaimKind.INJURY: Decimal("100000"),
    ClaimKind.PROPERTY: Decimal("10000"),
}
MAX_DOCUMENTS = 6


def _party(trip, user) -> str:
    if trip.rider.user_id == user.pk:
        return "rider"
    if trip.driver_id and trip.driver.user_id == user.pk:
        return "driver"
    raise ActionNotPermitted("Only the rider and driver of this trip can claim.")


@transaction.atomic
def file_claim(
    trip,
    *,
    user,
    kind: str,
    description: str,
    amount: Decimal,
    happened_at: datetime | None = None,
    files=(),
    now: datetime | None = None,
) -> InsuranceClaim:
    now = now or timezone.now()
    _party(trip, user)
    if kind not in ClaimKind.values:
        raise BusinessRuleViolation("Choose what happened.", field="kind")
    if trip.status not in ("IN_PROGRESS", "COMPLETED", "CANCELLED") or (
        trip.status != "IN_PROGRESS" and not trip.started_at
    ):
        raise BusinessRuleViolation("Cover starts when the ride starts.")
    ended = trip.completed_at or trip.cancelled_at
    if ended and now - ended > CLAIM_WINDOW:
        raise BusinessRuleViolation("Claims can be filed up to 7 days after the ride.")
    amount = Decimal(amount)
    if amount <= 0 or amount > COVER[kind]:
        raise BusinessRuleViolation(
            f"Up to ₹{COVER[kind]:,.0f} for this kind of claim.", field="amount"
        )
    if len(description.strip()) < 20:
        raise BusinessRuleViolation(
            "Describe what happened (at least a couple of sentences).", field="description"
        )
    if len(files) > MAX_DOCUMENTS:
        raise BusinessRuleViolation(f"Up to {MAX_DOCUMENTS} photos or documents.", field="files")
    claim = InsuranceClaim.objects.create(
        number=next_reference("CLM", year=timezone.localtime(now).year),
        trip=trip,
        claimant=user,
        kind=kind,
        description=description.strip()[:4000],
        happened_at=happened_at or trip.started_at or now,
        amount_claimed=amount,
        created_at=now,
    )
    for upload in files:
        ClaimDocument.objects.create(
            claim=claim, file=upload, label=getattr(upload, "name", "")[:80]
        )
    notify(
        user,
        f"Claim {claim.number} filed",
        "Our claims desk will review it within 2 working days.",
        link="/claims",
    )
    return claim


def start_review(claim: InsuranceClaim, *, reviewer) -> InsuranceClaim:
    if claim.status != ClaimStatus.SUBMITTED:
        raise InvalidStateTransition("This claim is already being handled.")
    claim.status, claim.reviewer = ClaimStatus.UNDER_REVIEW, reviewer
    claim.insurer_reference = f"INS-{claim.number[-8:]}"
    claim.save(update_fields=["status", "reviewer", "insurer_reference"])
    notify(claim.claimant, f"Claim {claim.number} is with the insurer", link="/claims")
    return claim


@transaction.atomic
def decide(
    claim: InsuranceClaim,
    *,
    reviewer,
    approve: bool,
    note: str,
    amount: Decimal | None = None,
    now: datetime | None = None,
) -> InsuranceClaim:
    """Approve (and pay into the wallet) or reject a claim under review."""
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post

    now = now or timezone.now()
    claim = InsuranceClaim.objects.select_for_update().get(pk=claim.pk)
    if claim.status not in (ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW):
        raise InvalidStateTransition("This claim has been decided.")
    if claim.claimant_id == reviewer.pk:
        raise ActionNotPermitted("You can't decide your own claim.")
    if len(note.strip()) < 10:
        raise BusinessRuleViolation("Explain the decision.", field="note")
    claim.reviewer, claim.decision_note, claim.decided_at = reviewer, note.strip(), now
    if approve:
        amount = Decimal(amount if amount is not None else claim.amount_claimed)
        if amount <= 0 or amount > claim.amount_claimed:
            raise BusinessRuleViolation("Approve up to the amount claimed.", field="amount")
        post(
            TransactionKind.INSURANCE,
            [(accounts.INSURER, -amount), (ensure_wallet(claim.claimant), amount)],
            trip=claim.trip,
            description=f"Insurance claim {claim.number}",
            actor=reviewer,
            at=now,
        )
        claim.status, claim.amount_approved, claim.paid_at = ClaimStatus.PAID, amount, now
    else:
        claim.status = ClaimStatus.REJECTED
    claim.save()
    notify(
        claim.claimant,
        f"Claim {claim.number}: "
        + (f"₹{claim.amount_approved:,.0f} paid to your wallet" if approve else "not approved"),
        note.strip()[:300],
        level=Level.SUCCESS if approve else Level.WARNING,
        link="/claims",
        email=True,
    )
    return claim
