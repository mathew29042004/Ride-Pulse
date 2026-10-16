from celery import shared_task

from . import services


@shared_task(name="tours.sweep")
def sweep() -> dict:
    return services.sweep()
