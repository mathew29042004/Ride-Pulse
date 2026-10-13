from celery import shared_task

from . import services


@shared_task(name="payments.create_weekly_payouts")
def create_weekly_payouts() -> int:
    return len(services.create_weekly_payouts())
