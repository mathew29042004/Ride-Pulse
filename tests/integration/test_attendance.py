"""Staff attendance: clock in against the roster (early window, grace, late), clock out (half
day), forgotten clock-outs closed, no-shows marked absent (leave isn't absence), corrections
approved by the manager, and the team board."""

from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.workspace import attendance
from apps.workspace.models import LeaveRequest, LeaveStatus, Shift

from ..conftest import make_staff

pytestmark = pytest.mark.django_db

_ids = iter(range(1, 10_000))
DAY = date(2026, 3, 2)


def at(h, m=0, day=DAY):
    return timezone.make_aware(datetime.combine(day, time(h, m)))


def hire(role, boss=None):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"A{next(_ids):05d}",
        title=role.title(),
        department="SUPPORT",
        state="Kerala",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    return user


@pytest.fixture
def team():
    lead = hire(Role.SUPPORT_LEAD)
    agent = hire(Role.SUPPORT_AGENT, lead.staff_profile)
    Shift.objects.create(user=agent, day=DAY, slot="MORNING", starts_at=at(6), ends_at=at(14))
    return lead, agent


def test_on_time_late_and_half_day(team):
    lead, agent = team
    with pytest.raises(BusinessRuleViolation, match="30 minutes"):
        attendance.clock_in(agent, now=at(5, 0))
    r = attendance.clock_in(agent, now=at(6, 8))  # within the 10-minute grace
    assert r.status == "WORKING" and r.late_minutes == 0
    with pytest.raises(BusinessRuleViolation, match="clocked in"):
        attendance.clock_in(agent, now=at(6, 9))
    r = attendance.clock_out(agent, now=at(14, 2))
    assert r.status == "PRESENT" and r.worked_minutes == 474

    other = hire(Role.SUPPORT_AGENT, lead.staff_profile)
    Shift.objects.create(user=other, day=DAY, slot="MORNING", starts_at=at(6), ends_at=at(14))
    r = attendance.clock_in(other, now=at(6, 40))
    assert r.late_minutes == 40
    assert attendance.clock_out(other, now=at(9)).status == "HALF_DAY"


def test_office_hours_for_people_without_shifts(team):
    lead, _ = team
    r = attendance.clock_in(lead, now=at(9, 50))
    assert r.shift is None and r.late_minutes == 20
    assert attendance.clock_out(lead, now=at(18, 45)).status == "LATE"


def test_close_day_absent_leave_and_forgotten_clock_out(team):
    lead, agent = team
    on_leave = hire(Role.SUPPORT_AGENT, lead.staff_profile)
    Shift.objects.create(user=on_leave, day=DAY, slot="MORNING", starts_at=at(6), ends_at=at(14))
    LeaveRequest.objects.create(
        user=on_leave,
        kind="SICK",
        starts_on=DAY,
        ends_on=DAY,
        status=LeaveStatus.APPROVED,
        created_at=at(5),
    )
    forgot = hire(Role.SUPPORT_AGENT, lead.staff_profile)
    Shift.objects.create(user=forgot, day=DAY, slot="MORNING", starts_at=at(6), ends_at=at(14))
    attendance.clock_in(forgot, now=at(6))

    stats = attendance.close_day(now=at(17))
    assert stats == {"closed": 1, "absent": 1, "leave": 1}
    assert attendance.Attendance.objects.get(user=agent).status == "ABSENT"
    assert attendance.Attendance.objects.get(user=on_leave).status == "ON_LEAVE"
    closed = attendance.Attendance.objects.get(user=forgot)
    assert closed.status == "NO_OUT" and closed.clock_out == at(14)
    assert attendance.close_day(now=at(18)) == {"closed": 0, "absent": 0, "leave": 0}


def test_corrections_go_to_the_manager(team, monkeypatch):
    lead, agent = team
    attendance.close_day(now=at(17))
    record = attendance.Attendance.objects.get(user=agent)
    monkeypatch.setattr(timezone, "localdate", lambda *a: DAY + timedelta(days=1))
    with pytest.raises(BusinessRuleViolation, match="why"):
        attendance.request_correction(
            record, user=agent, clock_in_at=at(6), clock_out_at=at(14), reason=""
        )
    attendance.request_correction(
        record,
        user=agent,
        clock_in_at=at(6),
        clock_out_at=at(14),
        reason="Biometric was down, I was on the floor",
    )
    stranger = hire(Role.SUPPORT_AGENT)
    with pytest.raises(ActionNotPermitted):
        attendance.decide_correction(record, manager=stranger, approve=True)
    record = attendance.decide_correction(record, manager=lead, approve=True)
    assert record.status == "PRESENT" and record.worked_minutes == 480
    board = attendance.team(lead, now=at(15))
    assert board["people"][0]["month"]["present"] == 1


def test_api(api):
    agent = hire(Role.SUPPORT_AGENT)
    client = api(agent)
    made = client.post("/api/v1/work/attendance/clock-in/")
    # Office hours are 9:30-6:30: depending on when the test runs it's allowed or refused.
    assert made.status_code in (200, 422)
    mine = client.get("/api/v1/work/attendance/").json()
    assert "month" in mine and "next" in mine


def test_clock_in_only_at_the_work_site(now):
    agent = hire(Role.SUPPORT_AGENT)
    StaffProfile.objects.filter(user=agent).update(
        work_lat=13.0418, work_lng=80.2341, work_radius_m=300
    )
    agent.refresh_from_db()
    Shift.objects.create(
        user=agent,
        day=now.date(),
        slot="MORNING",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=7),
    )
    with pytest.raises(BusinessRuleViolation, match="Allow location"):
        attendance.clock_in(agent, now=now)
    with pytest.raises(BusinessRuleViolation, match="km from your workplace"):
        attendance.clock_in(agent, now=now, lat=13.08, lng=80.27)
    assert attendance.clock_in(agent, now=now, lat=13.0420, lng=80.2343).clock_in
