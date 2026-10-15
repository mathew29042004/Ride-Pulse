"""Abuse protection: account lockout after repeated wrong passwords, and a security log.

* Five wrong passwords for one account within 15 minutes lock it for 15 minutes (a stolen
  password list can't be tried against it); the owner is told by email. Ops can unlock early.
* Every lock, unlock, failed login and rate-limit hit is logged (``SecurityEvent``), so the ops
  Security page shows attacks as they happen: top IPs, locked accounts, throttled endpoints.
* State lives in PostgreSQL, not a per-process cache, so it holds across every app server.
* Request rate limits (per IP, per user, and per endpoint: login, OTP, booking, GPS…) are DRF
  throttles configured in settings; SOS is never rate limited.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone

from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import SecurityEvent, SecurityKind

User = get_user_model()

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)
LOCK_KINDS = [SecurityKind.LOCKED, SecurityKind.UNLOCKED]


def client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


def _log(kind: str, *, email: str = "", request=None, detail: str = "", user=None, now=None):
    return SecurityEvent.objects.create(
        kind=kind,
        email=email.lower()[:254],
        ip=client_ip(request),
        path=(request.path[:200] if request is not None else ""),
        detail=detail[:200],
        user=user,
        created_at=now or timezone.now(),
    )


def locked_until(email: str, *, now: datetime | None = None) -> datetime | None:
    now = now or timezone.now()
    email = email.lower()
    last = (
        SecurityEvent.objects.filter(email=email, kind__in=LOCK_KINDS)
        .order_by("-created_at")
        .first()
    )
    if last is None or last.kind == SecurityKind.UNLOCKED:
        return None
    until = last.created_at + LOCK_FOR
    return until if until > now else None


def login_failed(email: str, *, request=None, now: datetime | None = None) -> datetime | None:
    """Record a wrong password; returns the lock expiry if this one locked the account."""
    now = now or timezone.now()
    email = email.lower()
    _log(SecurityKind.LOGIN_FAILED, email=email, request=request, now=now)
    since = now - WINDOW
    reset = SecurityEvent.objects.filter(email=email, kind__in=LOCK_KINDS).aggregate(
        at=Max("created_at")
    )["at"]
    if reset and reset > since:
        since = reset
    failures = SecurityEvent.objects.filter(
        email=email, kind=SecurityKind.LOGIN_FAILED, created_at__gte=since
    ).count()
    if failures < MAX_FAILURES:
        return None
    user = User.objects.filter(email__iexact=email).first()
    _log(
        SecurityKind.LOCKED,
        email=email,
        request=request,
        user=user,
        now=now,
        detail=f"{failures} wrong passwords in {int(WINDOW.total_seconds() // 60)} min",
    )
    if user:
        notify(
            user,
            "We locked your account for 15 minutes",
            "Someone entered the wrong password 5 times. If it wasn't you, change your password "
            "after the lock ends.",
            level=Level.DANGER,
            email=True,
        )
    return now + LOCK_FOR


def unlock(email: str, *, actor) -> None:
    _log(SecurityKind.UNLOCKED, email=email, user=actor, detail=f"by {actor.get_full_name()}")


def throttled(request, scope: str, wait: float | None) -> None:
    """Log a rate-limit hit, at most once a minute per IP and endpoint (attacks are noisy)."""
    ip = client_ip(request)
    key = f"sec:throttle:{ip}:{request.path}"
    if cache.add(key, 1, 60):
        user = getattr(request, "user", None)
        user = user if user is not None and user.is_authenticated else None
        _log(
            SecurityKind.THROTTLED,
            email=user.email if user else "",
            request=request,
            user=user,
            detail=f"{scope or 'default'} limit · retry in {int(wait or 0)} s",
        )


def overview(*, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    day = SecurityEvent.objects.filter(created_at__gte=now - timedelta(hours=24))
    locked = []
    for email in (
        SecurityEvent.objects.filter(kind=SecurityKind.LOCKED, created_at__gte=now - LOCK_FOR)
        .values_list("email", flat=True)
        .distinct()
    ):
        until = locked_until(email, now=now)
        if until:
            locked.append({"email": email, "until": until.isoformat()})
    return {
        "last_24h": dict(day.values_list("kind").annotate(n=Count("pk")).values_list("kind", "n")),
        "locked": locked,
        "top_ips": list(
            day.exclude(ip__isnull=True).values("ip").annotate(n=Count("pk")).order_by("-n")[:8]
        ),
        "top_paths": list(
            day.filter(kind=SecurityKind.THROTTLED)
            .values("path")
            .annotate(n=Count("pk"))
            .order_by("-n")[:8]
        ),
        "recent": [
            {
                "kind": e.kind,
                "label": e.get_kind_display(),
                "email": e.email,
                "ip": e.ip,
                "path": e.path,
                "detail": e.detail,
                "at": e.created_at.isoformat(),
            }
            for e in SecurityEvent.objects.all()[:40]
        ],
    }
