from celery import shared_task

from . import services


@shared_task(name="pricing.recompute_surge")
def recompute_surge() -> int:
    return len(services.recompute_surge())


@shared_task(name="pricing.check_price_alerts")
def check_price_alerts() -> dict:
    from . import alerts

    return alerts.check_alerts()
