"""Shifts and leave: the weekly roster respects rest, the weekly maximum and leave; approving
leave finds cover; new tickets go to the agent on duty."""

import itertools
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.support import services as support
from apps.workspace import roster
from apps.workspace.models import LeaveStatus, Shift

from ..conftest import make_staff

pytestmark = pytest.mark.django_db
_ids = iter(range(1, 10_000))


def hire(role, department, boss=None):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"R{next(_ids):05d}",
        title=role.title(),
        department=department,
        state="Kerala",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    return user


@pytest.fixture
def desk():
    lead = hire(Role.SUPPORT_LEAD, "SUPPORT")
    agents = [hire(Role.SUPPORT_AGENT, "SUPPORT", lead.staff_profile) for _ in range(6)]
    return lead, agents


def monday():
    today = timezone.localdate()
    return today - timedelta(days=today.weekday()) + timedelta(days=7)


def test_week_is_filled_within_the_rules(desk):
    _, agents = desk
    week = monday()
    result = roster.generate_week("Kerala", week)
    assert result["gaps"] == [] and result["shifts"] == 7 * 5  # 2 + 2 + 1 a day
    for agent in agents:
        mine = list(Shift.objects.filter(user=agent).order_by("starts_at"))
        assert len(mine) <= roster.MAX_SHIFTS_PER_WEEK
        assert len({s.day for s in mine}) == len(mine)  # never two shifts in a day
        for a, b in itertools.pairwise(mine):
            assert b.starts_at - a.ends_at >= roster.MIN_REST
    with pytest.raises(Exception, match="already rostered"):
        roster.generate_week("Kerala", week)


def test_approved_leave_is_covered_and_tickets_go_to_whoever_is_on_duty(desk, api):
    lead, _agents = desk
    week = monday()
    roster.generate_week("Kerala", week)
    absent = Shift.objects.filter(day=week).first().user
    leave = roster.request_leave(absent, kind="SICK", starts_on=week, ends_on=week, reason="Fever")
    outsider = hire(Role.SUPPORT_AGENT, "SUPPORT")
    with pytest.raises(Exception, match="above them"):
        roster.decide(leave, manager=outsider, approve=True)
    result = roster.decide(leave, manager=lead, approve=True)
    assert result["status"] == LeaveStatus.APPROVED and result["covered"] and not result["gaps"]
    assert not Shift.objects.filter(user=absent, day=week).exists()
    cover = Shift.objects.get(day=week, covering_for=absent)
    assert cover.user != absent

    on_shift = Shift.objects.filter(day=week, slot="MORNING").first()
    now = on_shift.starts_at + timedelta(hours=1)
    Shift.objects.filter(pk=on_shift.pk).update(
        starts_at=timezone.now() - timedelta(hours=1), ends_at=timezone.now() + timedelta(hours=1)
    )
    Shift.objects.exclude(pk=on_shift.pk).update(
        starts_at=now + timedelta(days=30), ends_at=now + timedelta(days=30, hours=8)
    )
    assert support.least_loaded_agent() == on_shift.user
