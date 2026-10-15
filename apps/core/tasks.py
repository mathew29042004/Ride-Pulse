"""Queueing background work safely."""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def enqueue(task, *args, **kwargs) -> None:
    """Queue a Celery task once the current transaction commits.

    The data is already saved by then, so a broker outage (Redis down) must not turn a
    successful request into an error: the extra (an email, a push) is skipped and logged.
    """

    def send() -> None:
        try:
            task.delay(*args, **kwargs)
        except Exception:
            logger.exception("Could not queue %s; skipped", getattr(task, "name", task))

    transaction.on_commit(send)
