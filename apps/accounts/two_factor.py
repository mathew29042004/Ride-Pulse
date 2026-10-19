"""Two-step sign-in for staff (TOTP, RFC 6238: the codes Google or Microsoft Authenticator show).

* **Set up**: the person gets a secret (typed or scanned into their authenticator app), proves
  it works with one code, and receives 10 one-time recovery codes (stored hashed, shown once).
* **Sign in**: after the right password, a staff member with two-step on gets a short-lived
  challenge instead of tokens; the code (or a recovery code) exchanges it for tokens. A code
  can't be reused, and wrong codes count towards the account lockout like wrong passwords.
* **Who must**: admins and managers (``REQUIRED_ROLES``) are shown that it's required until
  they turn it on; everyone else may.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

STEP = 30
DIGITS = 6
WINDOW = 1  # accept the previous and next 30 s as clocks drift
CHALLENGE_SALT = "rp.two-factor"
CHALLENGE_MAX_AGE = 300
REQUIRED_ROLES = {"COMMANDER", "ADMIN", "REGIONAL_MANAGER", "OPS_MANAGER"}
ISSUER = "Ride Pulse"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def code_at(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at if at is not None else time.time()) // STEP))


def provisioning_uri(secret: str, email: str) -> str:
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}"


def _matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int((at if at is not None else time.time()) // STEP)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


class TwoFactor(models.Model):
    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="two_factor"
    )
    secret = models.CharField(max_length=64)
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_step = models.BigIntegerField(default=0)  # no code is accepted twice
    recovery_codes = models.JSONField(default=list, blank=True)  # hashed

    class Meta:
        app_label = "accounts"

    def __str__(self) -> str:
        return f"2FA {self.user_id} {'on' if self.enabled_at else 'pending'}"


def is_enabled(user) -> bool:
    record = getattr(user, "two_factor", None) if user.pk else None
    try:
        return bool(record and record.enabled_at)
    except TwoFactor.DoesNotExist:
        return False


def required(user) -> bool:
    return user.role in REQUIRED_ROLES


def begin(user) -> dict:
    if not user.is_staff_member:
        raise BusinessRuleViolation("Two-step sign-in is for staff accounts.")
    if is_enabled(user):
        raise BusinessRuleViolation("Two-step sign-in is already on.")
    record, _ = TwoFactor.objects.update_or_create(
        user=user, defaults={"secret": new_secret(), "enabled_at": None, "recovery_codes": []}
    )
    return {"secret": record.secret, "uri": provisioning_uri(record.secret, user.email)}


@transaction.atomic
def enable(user, code: str, *, at: float | None = None) -> list[str]:
    record = TwoFactor.objects.select_for_update().filter(user=user).first()
    if record is None:
        raise BusinessRuleViolation("Start the set-up first.")
    step = _matching_step(record.secret, code, at)
    if step is None:
        raise BusinessRuleViolation(
            "That code didn't match. Check the time on your phone.", field="code"
        )
    codes = [f"{secrets.randbelow(10**8):08d}" for _ in range(10)]
    record.enabled_at = timezone.now()
    record.last_step = step
    record.recovery_codes = [make_password(c) for c in codes]
    record.save()
    return [f"{c[:4]}-{c[4:]}" for c in codes]


@transaction.atomic
def verify(user, code: str, *, at: float | None = None) -> bool:
    """A current code (once) or an unused recovery code."""
    record = (
        TwoFactor.objects.select_for_update().filter(user=user, enabled_at__isnull=False).first()
    )
    if record is None:
        return False
    step = _matching_step(record.secret, code, at)
    if step is not None and step > record.last_step:
        record.last_step = step
        record.save(update_fields=["last_step"])
        return True
    plain = "".join(ch for ch in str(code) if ch.isdigit())
    for i, hashed in enumerate(record.recovery_codes):
        if len(plain) == 8 and check_password(plain, hashed):
            record.recovery_codes = record.recovery_codes[:i] + record.recovery_codes[i + 1 :]
            record.save(update_fields=["recovery_codes"])
            return True
    return False


def disable(user, code: str) -> None:
    if not verify(user, code):
        raise BusinessRuleViolation("That code didn't match.", field="code")
    TwoFactor.objects.filter(user=user).delete()


def challenge_for(user) -> str:
    return signing.dumps({"u": user.pk}, salt=CHALLENGE_SALT)


def user_from_challenge(challenge: str):
    from apps.accounts.models import User

    try:
        data = signing.loads(challenge, salt=CHALLENGE_SALT, max_age=CHALLENGE_MAX_AGE)
    except signing.BadSignature:
        raise BusinessRuleViolation(
            "The sign-in took too long. Enter your password again."
        ) from None
    return User.objects.get(pk=data["u"], is_active=True)


def status(user) -> dict:
    record = TwoFactor.objects.filter(user=user).first()
    return {
        "enabled": bool(record and record.enabled_at),
        "required": required(user),
        "recovery_codes_left": len(record.recovery_codes) if record and record.enabled_at else 0,
    }


def coverage() -> dict:
    """For Platform health: who in a role that requires it hasn't turned it on."""
    from apps.accounts.models import User

    staff = User.objects.filter(is_active=True, staff_profile__isnull=False)
    on = set(TwoFactor.objects.filter(enabled_at__isnull=False).values_list("user_id", flat=True))
    must = staff.filter(role__in=REQUIRED_ROLES)
    return {
        "staff": staff.count(),
        "enabled": len(on),
        "required": must.count(),
        "required_missing": [
            {"id": u.pk, "name": u.get_full_name(), "role": u.role}
            for u in must.exclude(pk__in=on).order_by("first_name")[:50]
        ],
    }
