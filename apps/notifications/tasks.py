from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.core.conf import company_name

from .models import Notification


@shared_task(
    name="notifications.send_email",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=5,
)
def send_notification_email(notification_id: int) -> bool:
    notification = Notification.objects.select_related("user").filter(pk=notification_id).first()
    if notification is None or notification.emailed_at:
        return False
    send_mail(
        subject=f"[{company_name()}] {notification.title}",
        message=notification.body or notification.title,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification.user.email],
    )
    Notification.objects.filter(pk=notification_id).update(emailed_at=timezone.now())
    return True


@shared_task(name="notifications.send_push")
def send_push(
    user_id: int,
    title: str,
    body: str = "",
    url: str = "/",
    tag: str = "",
    ttl: int = 3600,
    urgent: bool = False,
) -> int:
    from . import push

    return push.send(user_id, title=title, body=body, url=url, tag=tag, ttl=ttl, urgent=urgent)


@shared_task(name="notifications.send_digests")
def send_digests() -> int:
    from .services import send_digests

    return send_digests()
