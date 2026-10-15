from celery import shared_task

from . import privacy


@shared_task(name="trust.privacy_daily")
def privacy_daily() -> dict:
    return {**privacy.run_due(), **privacy.purge()}
