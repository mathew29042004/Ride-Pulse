from celery import shared_task

from . import jobs, outbox, watchdog


@shared_task(name="reliability.relay_outbox")
def relay_outbox() -> dict:
    return {"published": outbox.relay(), **outbox.deliver_due()}


@shared_task(name="reliability.trip_watchdog")
def trip_watchdog() -> dict:
    return watchdog.sweep()


@shared_task(name="reliability.check_slow")
def check_slow() -> dict:
    return jobs.check_slow()
