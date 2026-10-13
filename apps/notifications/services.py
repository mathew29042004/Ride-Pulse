"""In-app notifications with optional email delivery through Celery."""

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.auth import get_user_model
from django.db import transaction

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
    notification = Notification.objects.create(
        user=user, title=title[:160], body=body, level=level, link=link
    )
    # Phone-only accounts have a placeholder address on the reserved .invalid domain.
    if email and user.email and not user.email.endswith(".invalid"):
        from .tasks import send_notification_email

        transaction.on_commit(lambda: send_notification_email.delay(notification.pk))
    _push(user, title=title[:160], body=body[:300], url=link or "/")
    return notification


def _push(user, **message) -> None:
    """Also deliver it as a phone/desktop notification, to devices that opted in."""
    from . import push
    from .models import PushSubscription

    if push.enabled() and PushSubscription.objects.filter(user=user).exists():
        from .tasks import send_push

        transaction.on_commit(lambda: send_push.delay(user.pk, **message))


def notify_users(users: Iterable, title: str, body: str = "", **kwargs) -> int:
    return sum(1 for user in users if notify(user, title, body, **kwargs))


def notify_role(role: str, title: str, body: str = "", **kwargs) -> int:
    users = get_user_model().objects.filter(role=role, is_active=True)
    return notify_users(users, title, body, **kwargs)


def unread_count(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)
