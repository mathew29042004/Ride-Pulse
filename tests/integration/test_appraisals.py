"""Appraisals: self-review, manager rating with evidence checks, raises applied on close."""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.workspace import appraisals, payroll
from apps.workspace.attendance import Attendance

from ..conftest import make_staff

pytestmark = pytest.mark.django_db
SELF = "I resolved most refund tickets within SLA and trained two new agents on the handbook."
GOOD = "Consistently fast and accurate with riders; a model for the team."


def hire(role, boss=None):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"R{user.pk:05d}",
        title=role.title(),
        department="SUPPORT",
        state="Kerala",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    payroll.SalaryStructure.objects.create(
        user=user, monthly_gross=Decimal(20_000), effective_from=date(2025, 1, 1)
    )
    return user


def test_cycle(api, admin, now):
    lead = hire(Role.SUPPORT_LEAD)
    agent, absent = (
        hire(Role.SUPPORT_AGENT, lead.staff_profile),
        hire(Role.SUPPORT_AGENT, lead.staff_profile),
    )
    for d in range(3):
        Attendance.objects.create(
            user=absent,
            day=now.date().replace(day=1 + d),
            expected_start=now,
            expected_end=now,
            status="ABSENT",
        )
    cycle = appraisals.start(by=admin, now=now)
    a = appraisals.Appraisal.objects.get(employee=agent)
    b = appraisals.Appraisal.objects.get(employee=absent)
    with pytest.raises(InvalidStateTransition):
        appraisals.rate(a, manager=lead, rating=4, comment=GOOD)
    with pytest.raises(ActionNotPermitted):
        appraisals.self_review(a, user=absent, text=SELF, rating=4)
    appraisals.self_review(a, user=agent, text=SELF, rating=4)
    appraisals.self_review(b, user=absent, text=SELF, rating=5)
    with pytest.raises(ActionNotPermitted):
        appraisals.rate(a, manager=agent, rating=4, comment=GOOD)
    appraisals.rate(a, manager=lead, rating=4, comment=GOOD)
    with pytest.raises(BusinessRuleViolation, match="3 absences"):
        appraisals.rate(b, manager=lead, rating=5, comment=GOOD)
    appraisals.rate(
        b,
        manager=lead,
        rating=5,
        comment="Outstanding because the absences were approved surgery days.",
    )
    result = appraisals.close(cycle, by=admin, now=now)
    assert result["raises"] == 2
    assert payroll.SalaryStructure.objects.get(user=agent).monthly_gross == Decimal("21800.00")
    assert payroll.SalaryStructure.objects.get(user=absent).monthly_gross == Decimal("22400.00")
    board = api(lead).get("/api/v1/work/appraisals/").json()
    assert len(board["team"]) == 2 and board["cycle"]["closed"]
