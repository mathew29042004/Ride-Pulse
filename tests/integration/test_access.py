"""Leavers, quarterly access reviews and joiners."""

from datetime import date, timedelta

import pytest
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, StaffProfile, User
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.workspace import access
from apps.workspace.models import Shift, WorkTask

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def hire(role, boss=None, joined=date(2025, 1, 1)):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"A{user.pk:05d}",
        title=role.title(),
        department="SUPPORT",
        state="Kerala",
        reports_to=boss,
        joined_on=joined,
    )
    return user


def test_offboarding_steps(api, admin, now):
    lead = hire(Role.SUPPORT_LEAD)
    agent = hire(Role.SUPPORT_AGENT, lead.staff_profile)
    token = RefreshToken.for_user(agent)
    WorkTask.objects.create(
        number="T-1",
        title="Call back",
        assignee=agent,
        assigned_by=lead,
        due_at=now + timedelta(days=1),
    )
    Shift.objects.create(
        user=agent,
        day=now.date(),
        slot="EVENING",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=8),
    )
    with pytest.raises(ActionNotPermitted):
        access.offboard(agent, by=agent, reason="Resigned")
    record = access.offboard(agent, by=admin, reason="Resigned, last day today", now=now)
    agent.refresh_from_db()
    assert not agent.is_active
    assert WorkTask.objects.get(number="T-1").assignee == lead
    assert not Shift.objects.filter(user=agent).exists()
    assert api(None).post("/api/v1/auth/token/refresh/", {"refresh": str(token)}).status_code == 401
    assert len(record.steps) == 6
    with pytest.raises(InvalidStateTransition):
        access.offboard(agent, by=admin, reason="Again please")


def test_review_keep_change_remove(admin):
    lead = hire(Role.SUPPORT_LEAD)
    a, b, c = (hire(Role.SUPPORT_AGENT, lead.staff_profile) for _ in range(3))
    review = access.start_review(by=admin)
    with pytest.raises(BusinessRuleViolation, match="already"):
        access.start_review(by=admin)
    items = {i.subject_id: i for i in review.items.all()}
    assert items[a.pk].reviewer == lead and items[a.pk].dormant
    with pytest.raises(ActionNotPermitted):
        access.decide(items[a.pk], reviewer=b, decision="KEEP")
    access.decide(items[a.pk], reviewer=lead, decision="KEEP")
    access.decide(items[b.pk], reviewer=lead, decision="CHANGE", new_role="FLEET_EXECUTIVE")
    with pytest.raises(BusinessRuleViolation, match="why"):
        access.decide(items[c.pk], reviewer=lead, decision="REMOVE")
    access.decide(items[c.pk], reviewer=lead, decision="REMOVE", note="Moved to a partner company")
    assert User.objects.get(pk=b.pk).role == "FLEET_EXECUTIVE"
    assert not User.objects.get(pk=c.pk).is_active
    assert access.review_progress(review)["done"] == 3


def test_api_and_joiners(api, admin, now):
    lead = hire(Role.SUPPORT_LEAD)
    hire(Role.SUPPORT_AGENT, lead.staff_profile, joined=now.date())
    assert api(admin).post("/api/v1/work/access/start/").status_code == 201
    mine = api(lead).get("/api/v1/work/access/").json()
    assert mine["mine"] and not mine["admin"]
    board = api(admin).get("/api/v1/work/access/").json()
    assert board["joiners"][0]["checks"]["Manager set"] and not board["joiners"][0]["done"]
    assert api(lead).post("/api/v1/work/access/start/").status_code == 403
