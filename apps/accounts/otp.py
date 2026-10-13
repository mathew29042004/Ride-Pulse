"""Phone-number login with one-time SMS codes, the way ride-hailing apps sign people in.

* Codes are 6 digits, valid for 5 minutes, and stored only as an HMAC (keyed with
  SECRET_KEY), so a database leak doesn't reveal live codes.
* 5 wrong guesses burn the code; a new code can be sent every 30 s, at most 5 per hour per
  number (on top of the per-IP API throttle), which stops SMS-bombing and brute force.
* A number nobody has used yet gets a short-lived signed token to finish signing up as a rider
  with just a name. Drivers and staff can sign in by phone only to accounts that exist.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.core.validators import normalize_indian_mobile

from . import sms
from .models import PhoneOTP, Role, User

CODE_TTL = timedelta(minutes=5)
RESEND_AFTER = timedelta(seconds=30)
MAX_PER_HOUR = 5
MAX_ATTEMPTS = 5
SIGNUP_TOKEN_MAX_AGE = 15 * 60  # seconds
SIGNUP_SALT = "ridepulse.phone-signup"


@dataclass(frozen=True)
class Challenge:
    phone: str
    expires_in: int
    resend_in: int
    debug_code: str | None = None  # only with the console SMS backend in DEBUG


def _hash(phone: str, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def normalize(phone: str) -> str:
    try:
        return normalize_indian_mobile(phone)
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), field="phone") from exc


def request_code(phone: str, *, ip: str | None = None) -> Challenge:
    phone = normalize(phone)
    now = timezone.now()
    recent = PhoneOTP.objects.filter(phone=phone, created_at__gte=now - timedelta(hours=1))
    last = recent.first()
    if last and now - last.created_at < RESEND_AFTER:
        wait = int((RESEND_AFTER - (now - last.created_at)).total_seconds()) + 1
        raise ConflictError(f"Please wait {wait} s before asking for another code.")
    if recent.count() >= MAX_PER_HOUR:
        raise ConflictError("Too many codes for this number. Try again in an hour.")
    user = User.objects.filter(phone=phone).first()
    if user and not user.is_active:
        raise BusinessRuleViolation("This account is disabled. Contact support.", field="phone")
    code = f"{secrets.randbelow(10**6):06d}"
    with transaction.atomic():
        # Any earlier code for this number stops working.
        PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=True).update(consumed_at=now)
        PhoneOTP.objects.create(
            phone=phone, code_hash=_hash(phone, code), expires_at=now + CODE_TTL, ip=ip
        )
    try:
        sms.send_login_code(phone, code)
    except sms.SMSError as exc:
        raise BusinessRuleViolation("We couldn't send the SMS. Try again shortly.") from exc
    debug = code if settings.DEBUG and sms.backend() == "console" else None
    return Challenge(phone, int(CODE_TTL.total_seconds()), int(RESEND_AFTER.total_seconds()), debug)


@dataclass(frozen=True)
class Verified:
    user: User | None  # None: a new number, finish with ``complete_signup``
    signup_token: str = ""


def verify_code(phone: str, code: str) -> Verified:
    phone = normalize(phone)
    now = timezone.now()
    error = ""
    with transaction.atomic():
        otp = (
            PhoneOTP.objects.select_for_update()
            .filter(phone=phone, consumed_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if otp is None:
            raise BusinessRuleViolation("This code has expired. Ask for a new one.", field="code")
        otp.attempts += 1
        if hmac.compare_digest(otp.code_hash, _hash(phone, (code or "").strip())):
            otp.consumed_at = now
        else:
            left = MAX_ATTEMPTS - otp.attempts
            if left <= 0:
                otp.consumed_at = now  # burn the code: no more guesses
            error = (
                f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left."
                if left > 0
                else "Too many wrong codes. Ask for a new one."
            )
        otp.save(update_fields=["attempts", "consumed_at"])
    # Raised only after the commit: raising inside the block would roll the attempt count
    # back, and the guess limit would never trigger.
    if error:
        raise BusinessRuleViolation(error, field="code")
    user = User.objects.filter(phone=phone).first()
    if user is not None:
        if user.role not in (Role.RIDER, Role.DRIVER):
            raise BusinessRuleViolation("Staff accounts sign in with email and password.")
        return Verified(user)
    return Verified(None, signing.dumps({"phone": phone}, salt=SIGNUP_SALT))


def complete_signup(signup_token: str, *, first_name: str, last_name: str = "", email: str = ""):
    """Create a rider for a verified new number. Returns the RiderProfile."""
    from apps.riders.services import register_rider

    try:
        phone = signing.loads(signup_token, salt=SIGNUP_SALT, max_age=SIGNUP_TOKEN_MAX_AGE)["phone"]
    except signing.BadSignature as exc:
        raise BusinessRuleViolation("Your verification expired. Start again.") from exc
    if User.objects.filter(phone=phone).exists():
        raise ConflictError("This number already has an account. Sign in instead.")
    if not first_name.strip():
        raise BusinessRuleViolation("Tell us your name.", field="first_name")
    return register_rider(
        # Phone-only accounts get a placeholder address on the reserved .invalid domain,
        # which is never emailed (see notifications).
        email=email.strip() or f"91{phone}@phone.invalid",
        password=None,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone,
    )
