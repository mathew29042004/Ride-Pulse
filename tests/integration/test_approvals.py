"""One approvals inbox: a manager sees their team's leave and claims, finance the big refunds."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Department, Role, StaffProfile
from apps.workspace.models import LeaveRequest

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def test_manager_sees_their_teams_requests(api):
    boss = make_staff(Role.OPS_MANAGER)
    agent = make_staff(Role.SUPPORT_AGENT)
    outsider = make_staff(Role.SUPPORT_AGENT)
    bp = StaffProfile.objects.create(
        user=boss,
        employee_id="A1",
        title="x",
        department=Department.OPERATIONS,
        joined_on=date(2024, 1, 1),
    )
    for i, u in enumerate([agent, outsider]):
        StaffProfile.objects.create(
            user=u,
            employee_id=f"A{i + 2}",
            title="x",
            department=Department.SUPPORT,
            joined_on=date(2024, 1, 1),
            reports_to=bp if u == agent else None,
        )
    today = timezone.localdate()
    for u in (agent, outsider):
        LeaveRequest.objects.create(
            user=u,
            kind="CASUAL",
            starts_on=today + timedelta(days=3),
            ends_on=today + timedelta(days=4),
            reason="Family function",
            created_at=timezone.now(),
        )
    r = api(boss).get("/api/v1/approvals/").json()
    assert r["count"] == 1 and agent.get_full_name() in r["items"][0]["title"]
    assert api(agent).get("/api/v1/approvals/").json()["count"] == 0


def test_finance_sees_large_refunds(api, rider, mini, make_driver, now):
    from apps.rides.models import Trip
    from apps.workspace import powers

    from .helpers import book, drive_to_completion

    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    Trip.objects.filter(pk=trip.pk).update(fare_total=Decimal(5000))
    powers.request_refund(
        trip=trip, amount=3000, reason="AC broken", actor=make_staff(Role.SUPPORT_LEAD)
    )
    items = api(make_staff(Role.FINANCE_MANAGER)).get("/api/v1/approvals/").json()["items"]
    assert [i["kind"] for i in items] == ["Refund"]
