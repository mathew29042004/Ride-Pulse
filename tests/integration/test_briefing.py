"""The chief of staff keeps the chief updated: updates and escalations reach the chief, decisions
with a proposed order issue it when approved, replies go back, and the auto-briefing runs."""

from datetime import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.exceptions import InvalidStateTransition
from apps.reliability import briefing, command
from apps.reliability.models import ChiefUpdate

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def test_update_reaches_the_chief_and_reply_goes_back(api):
    chief = make_staff(Role.COMMANDER)
    cos = make_staff(Role.CHIEF_OF_STAFF)
    r = api(cos).post(
        "/api/v1/ops/brief/",
        {"kind": "ESCALATION", "title": "Chennai airport queue is 40 deep"},
        format="json",
    )
    assert r.status_code == 201
    assert chief.notifications.filter(title__contains="Escalation").exists()
    inbox = api(chief).get("/api/v1/ops/chief/").json()
    assert inbox["unread"] == 1 and inbox["updates"][0]["kind"] == "ESCALATION"
    update_id = inbox["updates"][0]["id"]
    api(chief).post(f"/api/v1/ops/chief/updates/{update_id}/reply/", {"text": "Send 20 more"})
    assert cos.notifications.filter(title__startswith="The chief replied").exists()
    assert ChiefUpdate.objects.get().reply == "Send 20 more"
    assert api(cos).get("/api/v1/ops/chief/").status_code == 403  # the inbox is the chief's


def test_approving_a_decision_issues_its_order(api, chennai):
    chief = make_staff(Role.COMMANDER)
    cos = make_staff(Role.CHIEF_OF_STAFF)
    asked = (
        api(cos)
        .post(
            "/api/v1/ops/brief/ask/",
            {
                "title": "No surge in Chennai tonight?",
                "order": {"kind": "SURGE_OFF", "city": chennai.pk, "hours": 3},
            },
            format="json",
        )
        .json()
    )
    assert "Turn surge off in Chennai" in asked["order"]
    done = api(chief).post(
        f"/api/v1/ops/chief/decisions/{asked['id']}/decide/", {"approve": True}, format="json"
    )
    assert done.json()["status"] == "APPROVED"
    assert command.surge_cap(chennai) == 1
    assert cos.notifications.filter(title__startswith="The chief approved").exists()
    from apps.reliability.models import DecisionRequest

    with pytest.raises(InvalidStateTransition):
        briefing.decide(DecisionRequest.objects.get(), user=chief, approve=False)


def test_acting_commander_gets_the_updates(api):
    chief = make_staff(Role.COMMANDER)
    deputy = make_staff(Role.ADMIN)
    cos = make_staff(Role.CHIEF_OF_STAFF)
    command.delegate(user=chief, to=deputy, hours=2, reason="On a flight")
    briefing.send_update(user=cos, title="All quiet")
    assert deputy.notifications.filter(title__contains="All quiet").exists()


def test_auto_briefing_every_three_hours():
    make_staff(Role.COMMANDER)
    make_staff(Role.CHIEF_OF_STAFF)
    morning = timezone.make_aware(datetime(2026, 10, 19, 9, 0))
    assert briefing.auto_briefing(now=morning) == {"sent": 1}
    assert briefing.auto_briefing(now=morning) == {"sent": 0}  # not again within 3 hours
    night = timezone.make_aware(datetime(2026, 10, 19, 23, 30))
    assert briefing.auto_briefing(now=night) == {"sent": 0}  # the chief sleeps
    body = ChiefUpdate.objects.get().body
    assert "drivers live" in body and "open alerts" in body


def test_chief_of_staff_sees_but_cannot_command(api):
    cos = make_staff(Role.CHIEF_OF_STAFF)
    assert cos.has_capability("trips.view") and cos.has_capability("brief")
    assert not cos.has_capability("command") and not cos.has_capability("trips.manage")
    assert api(cos).get("/api/v1/ops/command/").status_code == 403
