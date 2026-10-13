from celery import shared_task

from . import services


@shared_task(name="pricing.recompute_surge")
def recompute_surge() -> int:
    return len(services.recompute_surge())
