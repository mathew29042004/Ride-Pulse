"""Support services that lock rows must work outside a test transaction too (pytest-django's
default transaction hides a missing ``@transaction.atomic``)."""

import pytest

from apps.accounts.models import Role
from apps.support import services as support
from apps.support.models import TicketStatus

from ..conftest import make_rider, make_staff


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_resolving_tickets_runs_in_its_own_transaction():
    rider = make_rider()
    agent = make_staff(Role.SUPPORT_AGENT)
    ticket = support.open_ticket(
        user=rider.user, category="OTHER", subject="Help", description="Something happened"
    )
    resolved = support.resolve(ticket, actor=agent, resolution="Sorted out on the phone")
    assert resolved.status == TicketStatus.RESOLVED

    other = support.open_ticket(
        user=rider.user, category="OTHER", subject="Lost item", description="Bag"
    )
    support.resolve_ticket_quietly(other, note="Returned")
    other.refresh_from_db()
    assert other.status == TicketStatus.RESOLVED
