from celery import shared_task

from . import dispatch, services


@shared_task(name="rides.dispatch_sweep")
def dispatch_sweep() -> dict:
    return dispatch.sweep()


@shared_task(name="rides.dispatch_scheduled_rides")
def dispatch_scheduled_rides() -> dict:
    return services.dispatch_scheduled_rides()
