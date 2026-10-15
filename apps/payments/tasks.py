from celery import shared_task

from . import services


@shared_task(name="payments.create_weekly_payouts")
def create_weekly_payouts() -> int:
    # Statements first: they withhold TDS from the balance that's about to be paid out.
    from apps.fleet.statements import generate_week

    generate_week()
    return len(services.create_weekly_payouts())
