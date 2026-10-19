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


@shared_task(name="rides.run_ride_checks")
def run_ride_checks() -> dict:
    from .safety import run_ride_checks as run

    return run()


@shared_task(name="rides.guardian_sweep")
def guardian_sweep() -> dict:
    from .guardian import sweep

    return sweep()


@shared_task(name="rides.lost_items_sweep")
def lost_items_sweep() -> dict:
    from .lost_items import sweep

    return sweep()


@shared_task(name="rides.follow_flights")
def follow_flights() -> dict:
    from .flights import follow

    return follow()
