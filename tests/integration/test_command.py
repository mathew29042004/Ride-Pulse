"""The commander: standing orders stop bookings and surge, the command centre is theirs alone,
and the commander and administrators sit in every team channel."""

import pytest

from apps.accounts.models import Role
from apps.core.exceptions import BusinessRuleViolation
from apps.pricing.models import RideType
from apps.reliability import command
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider, make_staff

pytestmark = pytest.mark.django_db


def test_orders_pause_bookings_then_lift(chennai):
    boss = make_staff(Role.COMMANDER)
    mini = RideType.objects.get(code="MINI")
    with pytest.raises(BusinessRuleViolation):
        command.issue(user=boss, kind="PAUSE_BOOKINGS", reason="short")  # reason too short
    order = command.issue(
        user=boss, kind="PAUSE_BOOKINGS", city=chennai, reason="Citywide bandh called today"
    )
    with pytest.raises(BusinessRuleViolation, match="bandh"):
        rides.request_trip(
            rider=make_rider(), ride_type=mini, pickup=T_NAGAR, dropoff=MARINA, payment_method="UPI"
        )
    command.lift(order, user=boss)
    assert command.refusal(chennai, "CAR") is None


def test_pause_one_vehicle_everywhere_and_surge_off(chennai):
    boss = make_staff(Role.COMMANDER)
    command.issue(
        user=boss, kind="PAUSE_VEHICLE", vehicle_code="BIKE", reason="Bike taxi rules under review"
    )
    assert "Bike taxis" in command.refusal(chennai, "BIKE")
    assert command.refusal(chennai, "CAR") is None
    assert command.surge_cap(chennai) is None
    command.issue(user=boss, kind="SURGE_OFF", city=chennai, reason="Festival: no surge today")
    assert command.surge_cap(chennai) == 1


def test_only_the_commander_uses_the_command_centre(api, admin, chennai):
    boss = make_staff(Role.COMMANDER)
    assert api(admin).get("/api/v1/ops/command/").status_code == 403
    r = api(boss).get("/api/v1/ops/command/")
    assert r.status_code == 200 and any(c["name"] == "Chennai" for c in r.json()["cities"])
    made = api(boss).post(
        "/api/v1/ops/command/",
        {"kind": "SURGE_OFF", "city": chennai.pk, "reason": "Heavy traffic, keep fares fair"},
        format="json",
    )
    assert made.status_code == 201 and made.json()["active"]
    lifted = api(boss).post(f"/api/v1/ops/command/{made.json()['id']}/lift/")
    assert lifted.status_code == 200 and not lifted.json()["active"]
    sent = api(boss).post(
        "/api/v1/ops/command/broadcast/",
        {"title": "Thank you", "body": "Record week.", "audiences": ["STAFF", "DRIVERS"]},
        format="json",
    )
    assert sent.json() == {"sent": 2}


def test_commander_and_admin_join_every_channel(admin):
    from apps.accounts.models import Department, StaffProfile
    from apps.chat.models import Conversation, Member
    from apps.chat.services import sync_channels

    agent = make_staff(Role.SUPPORT_AGENT)
    for i, (user, dept) in enumerate([(admin, Department.LEADERSHIP), (agent, Department.SUPPORT)]):
        StaffProfile.objects.create(
            user=user, employee_id=f"T{i}", title="x", department=dept, joined_on="2024-01-01"
        )
    command.seed_commander(log=lambda *_: None)
    sync_channels()
    boss = StaffProfile.objects.get(user__role=Role.COMMANDER)
    assert StaffProfile.objects.get(user=admin).reports_to == boss
    support = Conversation.objects.get(kind="CHANNEL", slug="support")
    members = set(Member.objects.filter(conversation=support).values_list("user_id", flat=True))
    assert {admin.pk, boss.user_id, agent.pk} <= members


def test_pausing_every_city_needs_confirmation():
    boss = make_staff(Role.COMMANDER)
    with pytest.raises(BusinessRuleViolation, match="Confirm"):
        command.issue(user=boss, kind="PAUSE_BOOKINGS", reason="Payment gateway is down")
    order = command.issue(
        user=boss, kind="PAUSE_BOOKINGS", reason="Payment gateway is down", confirm=True
    )
    assert order.city is None


def test_delegation_gives_and_takes_back_command(api):
    boss = make_staff(Role.COMMANDER)
    deputy = make_staff(Role.ADMIN)
    agent = make_staff(Role.SUPPORT_AGENT)
    assert not deputy.has_capability("command")
    with pytest.raises(BusinessRuleViolation):
        command.delegate(user=boss, to=agent, hours=4, reason="Travelling")
    with pytest.raises(BusinessRuleViolation):
        command.delegate(user=deputy, to=deputy, hours=4, reason="Travelling")
    r = api(boss).post(
        "/api/v1/ops/command/delegate/",
        {"to": deputy.pk, "hours": 4, "reason": "Travelling"},
        format="json",
    )
    assert r.status_code == 201
    assert deputy.has_capability("command") and "command" in deputy.capabilities
    assert api(deputy).get("/api/v1/ops/command/").status_code == 200
    assert (
        api(deputy)
        .post("/api/v1/ops/command/delegate/", {"to": deputy.pk, "reason": "again"}, format="json")
        .status_code
        == 422
    )  # an acting commander can't hand command on
    api(boss).post(f"/api/v1/ops/command/delegations/{r.json()['id']}/revoke/")
    assert not deputy.has_capability("command")


def test_watchtower_raises_once_and_acknowledges(api, chennai):
    from datetime import timedelta

    from django.utils import timezone

    from apps.reliability.models import CommandAlert
    from apps.rides.models import Trip, TripStatus

    boss = make_staff(Role.COMMANDER)
    mini = RideType.objects.get(code="MINI")
    for _ in range(command.STRANDED):
        rides.request_trip(
            rider=make_rider(), ride_type=mini, pickup=T_NAGAR, dropoff=MARINA, payment_method="UPI"
        )
    assert Trip.objects.filter(status=TripStatus.REQUESTED).count() == command.STRANDED
    assert command.watch()["alerts_raised"] == 1
    assert command.watch()["alerts_raised"] == 0  # still open: no duplicate
    alert = CommandAlert.objects.get()
    assert "Chennai" in alert.title
    assert boss.notifications.filter(title=alert.title).exists()
    r = api(boss).post(f"/api/v1/ops/command/alerts/{alert.pk}/acknowledge/")
    assert r.json()["acknowledged_by"]
    later = timezone.now() + timedelta(minutes=10)
    assert command.watch(now=later)["alerts_raised"] == 0  # acknowledged recently: no nagging


def test_find_and_act_on_people(api, make_driver):
    boss = make_staff(Role.COMMANDER)
    driver = make_driver(online=False)
    found = api(boss).get(f"/api/v1/ops/command/people/?q={driver.user.email}").json()["results"]
    assert found[0]["kind"] == "driver" and found[0]["id"] == driver.pk
    bad = api(boss).post(
        "/api/v1/ops/command/act/",
        {"kind": "driver", "id": driver.pk, "action": "suspend"},
        format="json",
    )
    assert bad.status_code == 422  # a reason is required
    ok = api(boss).post(
        "/api/v1/ops/command/act/",
        {"kind": "driver", "id": driver.pk, "action": "suspend", "reason": "Repeated speeding"},
        format="json",
    )
    assert ok.status_code == 200
    driver.refresh_from_db()
    assert driver.onboarding_status == "SUSPENDED"
    rider = make_rider()
    api(boss).post(
        "/api/v1/ops/command/act/",
        {"kind": "rider", "id": rider.pk, "action": "block", "reason": "Abusive to drivers"},
        format="json",
    )
    rider.refresh_from_db()
    assert rider.is_blocked
