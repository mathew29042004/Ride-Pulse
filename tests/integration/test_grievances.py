"""Grievance officer desk: filing (riders and drivers only, real detail), acknowledgement and
resolution deadlines, automatic escalation when late, one escalation by the person after a
resolution, the public officer page and the compliance check."""

from datetime import timedelta

import pytest

from apps.accounts.models import Role
from apps.compliance.checks import state_report
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.trust import grievances

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db
TEXT = "The driver took a much longer route and refused to follow the map, then charged me more."


def test_file_acknowledge_resolve_and_escalate(ops, now):
    rider = make_rider()
    appellate = make_staff(Role.REGIONAL_MANAGER)
    with pytest.raises(BusinessRuleViolation, match="what happened"):
        grievances.file(rider.user, category="FARE", subject="Overcharged", description="Too much")
    with pytest.raises(ActionNotPermitted):
        grievances.file(ops, category="FARE", subject="Overcharged", description=TEXT)
    g = grievances.file(
        rider.user,
        category="FARE",
        subject="Overcharged on airport trip",
        description=TEXT,
        now=now,
    )
    assert g.ack_due == now + timedelta(hours=48) and g.resolve_due == now + timedelta(days=15)

    grievances.acknowledge(g, user=ops, now=now + timedelta(hours=3))
    with pytest.raises(InvalidStateTransition):
        grievances.acknowledge(g, user=ops)
    with pytest.raises(BusinessRuleViolation, match="resolution"):
        grievances.resolve(g, user=ops, resolution="Done")
    with pytest.raises(InvalidStateTransition):
        grievances.escalate(g, reason="I want a manager now", by=rider.user)  # not resolved yet
    grievances.resolve(
        g, user=ops, resolution="Route was 6 km longer than needed; ₹140 refunded to your wallet."
    )
    other = make_rider(first_name="Other")
    with pytest.raises(ActionNotPermitted):
        grievances.escalate(g, reason="Not good enough at all", by=other.user)
    grievances.escalate(g, reason="Refund doesn't cover the waiting time", by=rider.user)
    g.refresh_from_db()
    assert g.status == "ESCALATED" and g.appellate_officer == appellate and g.satisfied is False
    with pytest.raises(InvalidStateTransition):
        grievances.escalate(g, reason="Once more please, again", by=rider.user)


def test_late_ones_escalate_by_themselves(make_driver, now):
    make_staff(Role.REGIONAL_MANAGER)
    driver = make_driver(online=False)
    g = grievances.file(
        driver.user,
        category="ACCOUNT",
        subject="Suspended without reason",
        description=TEXT,
        now=now,
    )
    assert grievances.sweep(now=now + timedelta(hours=47)) == {
        "late_acknowledgement": 0,
        "late_resolution": 0,
    }
    assert grievances.sweep(now=now + timedelta(hours=49))["late_acknowledgement"] == 1
    g.refresh_from_db()
    assert g.status == "ESCALATED" and "48 hours" in g.escalation_reason


def test_api_public_page_and_compliance(api, ops, now):
    rider = make_rider()
    made = api(rider.user).post(
        "/api/v1/me/grievances/",
        {"category": "CONDUCT", "subject": "Rude driver at pickup", "description": TEXT},
        format="json",
    )
    assert made.status_code == 201
    mine = api(rider.user).get("/api/v1/me/grievances/").json()
    assert mine["officer"]["email"] and mine["grievances"][0]["number"] == made.json()["number"]
    queue = api(ops).get("/api/v1/ops/trust/grievances/")
    assert queue.status_code in (200, 403)
    admin = make_staff(Role.ADMIN)
    gid = made.json()["id"]
    assert (
        api(admin).post(f"/api/v1/ops/trust/grievances/{gid}/acknowledge/").json()["status"]
        == "ACKNOWLEDGED"
    )
    public = api(None).get("/api/v1/grievance-officer/").json()
    assert public["acknowledge_within_hours"] == 48 and public["resolve_within_days"] == 15
    check = next(c for c in state_report("Tamil Nadu")["checks"] if c["key"] == "grievance_officer")
    assert check["status"] == "OK" and "1 received" in check["detail"]
