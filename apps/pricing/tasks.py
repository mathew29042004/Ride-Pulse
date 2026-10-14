from celery import shared_task

from . import services


@shared_task(name="pricing.recompute_surge")
def recompute_surge() -> int:
    return len(services.recompute_surge())


@shared_task(name="pricing.check_price_alerts")
def check_price_alerts() -> dict:
    from . import alerts

    return alerts.check_alerts()


@shared_task(name="pricing.sync_city_coverage")
def sync_city_coverage() -> dict:
    """Pause ride types no approved driver in a city can serve; resume them when one can."""
    from .coverage import sync

    return sync()
