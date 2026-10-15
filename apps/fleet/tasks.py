from celery import shared_task

from . import maintenance, quests


@shared_task(name="fleet.upkeep_sweep")
def upkeep_sweep() -> dict:
    return maintenance.sweep()


@shared_task(name="fleet.end_quests")
def end_quests() -> int:
    return quests.end_finished()
