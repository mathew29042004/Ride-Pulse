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


@shared_task(name="reliability.nightly_backup")
def nightly_backup() -> dict:
    from .backups import backup

    return backup()


@shared_task(name="reliability.restore_drill")
def weekly_restore_drill() -> dict:
    from .backups import restore_drill

    return restore_drill()


@shared_task(name="reliability.watchtower")
def watchtower() -> dict:
    from .command import watch

    return watch()
