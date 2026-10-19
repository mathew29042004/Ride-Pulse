"""In-app notifications with optional email delivery through Celery."""

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.auth import get_user_model

from apps.core.tasks import enqueue

from .models import Level, Notification

_muted: ContextVar[bool] = ContextVar("notifications_muted", default=False)


@contextmanager
def muted():
    """Suppress notifications, e.g. while bulk-loading demo data."""
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)


def notify(
    user,
    title: str,
    body: str = "",
    *,
    level: str = Level.INFO,
    link: str = "",
    email: bool = False,
) -> Notification | None:
    if user is None or _muted.get() or not user.is_active:
        return None
    held = _hold(user, level)
    notification = Notification.objects.create(
        user=user, title=title[:160], body=body, level=level, link=link, held=held
    )
    # Phone-only accounts have a placeholder address on the reserved .invalid domain.
    if email and user.email and not user.email.endswith(".invalid"):
        from .tasks import send_notification_email

        enqueue(send_notification_email, notification.pk)
    if not held:
        _push(user, title=title[:160], body=body[:300], url=link or "/")
    return notification


ROUTINE = {Level.INFO, Level.SUCCESS}


def _hold(user, level: str) -> bool:
    """Urgent things always get through; routine ones wait for the digest or quiet hours."""
    from django.utils import timezone

    from .models import NotificationPreference

    if level == Level.DANGER:
        return False
    pref = NotificationPreference.objects.filter(user=user).first()
    if pref is None:
        return False
    return (pref.digest and level in ROUTINE) or pref.is_quiet(timezone.now())


def send_digests(*, now=None) -> int:
    """Each morning: one summary of the routine updates held since yesterday."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import NotificationPreference

    now = now or timezone.now()
    sent = 0
    for pref in NotificationPreference.objects.filter(digest=True).select_related("user"):
        held = Notification.objects.filter(
            user=pref.user, held=True, is_read=False, created_at__gte=now - timedelta(days=1)
        )
        titles = list(held.values_list("title", flat=True)[:8])
        if not titles:
            continue
        n = held.count()
        body = "\n".join(f"• {t}" for t in titles) + (f"\n…and {n - 8} more" if n > 8 else "")
        Notification.objects.create(
            user=pref.user, title=f"Your daily digest: {n} updates", body=body, link=""
        )
        _push(pref.user, title=f"Your daily digest: {n} updates", body=body[:300], url="/")
        sent += 1
    return sent


def _push(user, **message) -> None:
    """Also deliver it as a phone/desktop notification, to devices that opted in."""
    from . import push
    from .models import PushSubscription

    if push.enabled() and PushSubscription.objects.filter(user=user).exists():
        from .tasks import send_push

        enqueue(send_push, user.pk, **message)


def notify_users(users: Iterable, title: str, body: str = "", **kwargs) -> int:
    return sum(1 for user in users if notify(user, title, body, **kwargs))


def notify_role(role: str, title: str, body: str = "", **kwargs) -> int:
    users = get_user_model().objects.filter(role=role, is_active=True)
    return notify_users(users, title, body, **kwargs)


def unread_count(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)
