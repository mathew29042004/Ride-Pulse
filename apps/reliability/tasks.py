from celery import shared_task

from . import outbox


@shared_task(name="reliability.relay_outbox")
def relay_outbox() -> dict:
    return {"published": outbox.relay(), **outbox.deliver_due()}
