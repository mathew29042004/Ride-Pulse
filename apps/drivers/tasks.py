from celery import shared_task

from . import services


@shared_task(name="drivers.mark_stale_drivers_offline")
def mark_stale_drivers_offline() -> int:
    return services.mark_stale_drivers_offline()


@shared_task(name="drivers.check_document_expiry")
def check_document_expiry() -> dict:
    return services.check_document_expiry()


@shared_task(name="drivers.purge_location_pings")
def purge_location_pings() -> int:
    return services.purge_location_pings()


@shared_task(name="drivers.wellbeing_sweep")
def wellbeing_sweep() -> dict:
    from .wellbeing import sweep

    return sweep()
