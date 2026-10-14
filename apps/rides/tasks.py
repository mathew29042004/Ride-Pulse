from celery import shared_task

from . import dispatch, services


@shared_task(name="rides.dispatch_sweep")
def dispatch_sweep() -> dict:
    return dispatch.sweep()


@shared_task(name="rides.dispatch_scheduled_rides")
def dispatch_scheduled_rides() -> dict:
    return services.dispatch_scheduled_rides()


@shared_task(
    name="rides.email_invoice", autoretry_for=(OSError,), retry_backoff=True, max_retries=5
)
def email_invoice(trip_id: int, force: bool = False) -> bool:
    from .invoices import send
    from .models import Trip

    trip = Trip.objects.filter(pk=trip_id).first()
    return bool(trip) and send(trip, force=force)
