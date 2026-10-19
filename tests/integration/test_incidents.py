"""Incidents: open, update, resolve, review (follow-ups become tasks); the public status page
and the in-app banner follow the open incidents; only ops can run them."""

import pytest

from apps.accounts.models import Role
from apps.workspace.models import WorkTask

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db


def test_incident_lifecycle_status_page_and_banners(api, make_driver, now):
    from datetime import date

    from apps.accounts.models import StaffProfile

    manager = make_staff(Role.OPS_MANAGER)
    engineer = make_staff(Role.SUPPORT_LEAD)
    boss = StaffProfile.objects.create(
        user=manager,
        employee_id="I0001",
        title="Ops manager",
        department="OPERATIONS",
        joined_on=date(2025, 1, 1),
    )
    StaffProfile.objects.create(  # follow-ups go to people in your team
        user=engineer,
        employee_id="I0002",
        title="Support lead",
        department="SUPPORT",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    ops = api(manager)
    incident = ops.post(
        "/api/v1/ops/incidents/",
        {
            "title": "Card payments failing",
            "severity": "MAJOR",
            "components": ["PAYMENTS"],
            "public_message": "Card payments are delayed. UPI and cash work as usual.",
        },
        format="json",
    ).json()
    public = api(None).get("/api/v1/status/").json()
    assert public["overall"] == "PARTIAL"
    assert next(c for c in public["components"] if c["key"] == "PAYMENTS")["state"] == "PARTIAL"
    rider = api(make_rider().user)
    assert (
        rider.get("/api/v1/status/banner/").json()["banner"]["message"].startswith("Card payments")
    )

    driver_only = ops.post(
        "/api/v1/ops/incidents/",
        {
            "title": "Driver app slow",
            "severity": "MINOR",
            "components": ["DRIVER_APP"],
            "public_message": "Going online may take a minute.",
        },
        format="json",
    ).json()
    driver = api(make_driver(now=now).user)
    assert (
        driver.get("/api/v1/status/banner/").json()["banner"]["number"] == incident["number"]
    )  # worse one first
    for i in (incident, driver_only):
        ops.post(
            f"/api/v1/ops/incidents/{i['id']}/progress/",
            {"status": "RESOLVED", "message": "Fixed and verified"},
            format="json",
        )
    assert rider.get("/api/v1/status/banner/").json()["banner"] is None
    assert api(None).get("/api/v1/status/").json()["overall"] == "OPERATIONAL"

    reviewed = ops.post(
        f"/api/v1/ops/incidents/{incident['id']}/review/",
        {
            "summary": "Card payments failed for 40 minutes after a gateway key expired.",
            "root_cause": "The gateway key wasn't monitored for expiry.",
            "actions": [
                {"title": "Alert 30 days before keys expire", "assignee_id": engineer.pk, "days": 7}
            ],
        },
        format="json",
    ).json()
    assert reviewed.get("reviewed_at"), reviewed
    assert len(reviewed["tasks"]) == 1
    assert WorkTask.objects.get(assignee=engineer).title.startswith(incident["number"])
    assert api(make_staff(Role.SUPPORT_AGENT)).post("/api/v1/ops/incidents/", {}).status_code == 403


def test_major_incident_gets_a_war_room(api):
    from datetime import date

    from apps.accounts.models import StaffProfile
    from apps.chat.models import Conversation, Message
    from apps.reliability import incidents

    manager = make_staff(Role.OPS_MANAGER)
    chief = make_staff(Role.COMMANDER)
    for i, u in enumerate([manager, chief]):
        StaffProfile.objects.create(
            user=u,
            employee_id=f"W{i}",
            title="x",
            department="OPERATIONS",
            joined_on=date(2025, 1, 1),
        )
    inc = incidents.open_incident(
        user=manager,
        title="Maps down",
        severity="MAJOR",
        components=["MAPS"],
        public_message="Maps are slow, pickups may take longer.",
    )
    room = Conversation.objects.get(incident=inc)
    assert set(room.members.values_list("user_id", flat=True)) == {manager.pk, chief.pk}
    incidents.update(inc, user=manager, status="RESOLVED", message="Provider fixed it")
    bodies = list(Message.objects.filter(conversation=room).values_list("body", flat=True))
    assert bodies[0].startswith("🚨 War room") and "Live numbers now" in bodies[-1]
    row = api(manager).get("/api/v1/ops/incidents/").json()
    rows = row["results"] if isinstance(row, dict) and "results" in row else row
    assert any(
        r.get("war_room") == room.pk
        for r in (rows if isinstance(rows, list) else rows["incidents"])
    )
