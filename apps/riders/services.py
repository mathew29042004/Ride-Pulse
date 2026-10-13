import secrets
import string

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import Role
from apps.audit.models import AuditAction
from apps.audit.services import log_event
from apps.core.exceptions import BusinessRuleViolation

from .models import RiderProfile

_ALPHABET = string.ascii_uppercase + string.digits


def new_referral_code() -> str:
    while True:
        code = "RP" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not RiderProfile.objects.filter(referral_code=code).exists():
            return code


@transaction.atomic
def register_rider(
    *,
    email: str,
    password: str | None,
    first_name: str,
    last_name: str = "",
    phone: str = "",
    referral_code: str = "",
) -> RiderProfile:
    from apps.payments.services import ensure_wallet

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        raise BusinessRuleViolation("An account with this email already exists.", field="email")
    referrer = None
    if referral_code:
        referrer = RiderProfile.objects.filter(referral_code=referral_code.upper()).first()
        if referrer is None:
            raise BusinessRuleViolation("That referral code is not valid.", field="referral_code")
    user = User.objects.create_user(
        email=email,
        password=password,
        role=Role.RIDER,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    profile = RiderProfile.objects.create(
        user=user, referral_code=new_referral_code(), referred_by=referrer
    )
    ensure_wallet(user)
    return profile


@transaction.atomic
def set_blocked(
    rider: RiderProfile, blocked: bool, *, reason: str = "", actor=None
) -> RiderProfile:
    if blocked and not reason.strip():
        raise BusinessRuleViolation("A reason is required to block a rider.", field="reason")
    rider.is_blocked = blocked
    rider.blocked_reason = reason if blocked else ""
    rider.save(update_fields=["is_blocked", "blocked_reason", "updated_at"])
    log_event(
        AuditAction.ACTION,
        rider,
        message=("Blocked: " + reason) if blocked else "Unblocked",
        actor=actor,
    )
    return rider
