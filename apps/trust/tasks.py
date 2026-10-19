from celery import shared_task

from . import privacy


@shared_task(name="trust.privacy_daily")
def privacy_daily() -> dict:
    return {**privacy.run_due(), **privacy.purge()}


@shared_task(name="trust.grievance_sweep")
def grievance_sweep() -> dict:
    """Escalate grievances that missed the 48-hour or 15-day deadline."""
    from .grievances import sweep

    return sweep()
