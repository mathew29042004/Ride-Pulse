from celery import shared_task

from . import services


@shared_task(name="workspace.flag_overdue")
def flag_overdue() -> int:
    return services.flag_overdue()


@shared_task(name="workspace.roll_daily_standups")
def roll_daily_standups() -> int:
    return services.roll_daily_standups()


@shared_task(name="workspace.close_attendance")
def close_attendance() -> dict:
    from .attendance import close_day

    return close_day()


@shared_task(name="workspace.chase_access_reviews")
def chase_access_reviews() -> int:
    from .access import chase

    return chase()


@shared_task(name="workspace.celebrate")
def celebrate() -> dict:
    from .culture import celebrate

    return celebrate()
