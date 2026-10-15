from celery import shared_task

from . import services


@shared_task(name="workspace.flag_overdue")
def flag_overdue() -> int:
    return services.flag_overdue()


@shared_task(name="workspace.roll_daily_standups")
def roll_daily_standups() -> int:
    return services.roll_daily_standups()
