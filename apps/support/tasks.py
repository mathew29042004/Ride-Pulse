from celery import shared_task

from . import services


@shared_task(name="support.escalate_sla_breaches")
def escalate_sla_breaches() -> int:
    return services.escalate_sla_breaches()
