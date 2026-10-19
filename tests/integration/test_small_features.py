"""Small features: ask the chief of staff, leaderboard thanks, scheduled orders, birthdays and
anniversaries, shift handovers, a driver's earnings goal."""

import itertools
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Department, Role, StaffProfile
from apps.chat.models import Conversation, Message
from apps.chat.services import sync_channels
from apps.reliability import command
from apps.workspace import culture

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


_ids = itertools.count(1)


def _staff(role, *, city=None, joined=date(2024, 1, 1), dob=None):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"S{next(_ids)}",
        title=role.title(),
        department=Department.OPERATIONS,
        city=city,
        joined_on=joined,
        date_of_birth=dob,
    )
    return user


def test_ask_the_chief_of_staff(api, chennai):
    chief = make_staff(Role.COMMANDER)
    make_staff(Role.CHIEF_OF_STAFF)
    r = api(chief).post(
        "/api/v1/ops/chief/question/", {"question": "How is Chennai today? any SOS?"}
    )
    body = r.json()["body"]
    assert "Chennai today" in body and "SOS open" in body


def test_scheduled_order_starts_later(chennai):
    chief = make_staff(Role.COMMANDER)
    later = timezone.now() + timedelta(hours=5)
    order = command.issue(
        user=chief,
        kind="SURGE_OFF",
        city=chennai,
        reason="Diwali evening, no surge",
        starts_at=later,
    )
    assert command.surge_cap(chennai) is None  # not yet
    assert command.surge_cap(chennai, now=later + timedelta(minutes=1)) == 1
    assert command.row(order)["scheduled"]


def test_thanks_and_celebrations():
    chief = make_staff(Role.COMMANDER)
    today = timezone.localdate()
    bday = _staff(Role.SUPPORT_AGENT, dob=date(1995, today.month, today.day))
    _staff(Role.FLEET_EXECUTIVE, joined=date(today.year - 3, today.month, today.day))
    sync_channels()
    assert culture.celebrate() == {"posted": 2}
    assert culture.celebrate() == {"posted": 0}  # once a day
    general = Conversation.objects.get(slug="general")
    bodies = list(Message.objects.filter(conversation=general).values_list("body", flat=True))
    assert any("Happy birthday" in b for b in bodies) and any("3 years" in b for b in bodies)
    assert bday.notifications.exists()
    with pytest.raises(Exception, match="Nobody to thank"):
        command.thank(user=chief, kind="driver")


def test_handover_reaches_the_next_shift(api, chennai):
    day = _staff(Role.DISPATCH_CONTROLLER, city=chennai)
    night = _staff(Role.DISPATCH_CONTROLLER, city=chennai)
    api(day).post("/api/v1/work/attendance/handover/", {"body": "Airport queue long, watch T1"})
    notes = api(night).get("/api/v1/work/attendance/handovers/").json()["notes"]
    assert notes[0]["body"].startswith("Airport queue") and notes[0]["author"]
    assert api(day).get("/api/v1/work/attendance/handovers/").json()["notes"] == []


def test_driver_earnings_goal(api, make_driver):
    driver = make_driver(online=False)
    r = api(driver.user).post("/api/v1/driver/earnings-goal/", {"amount": 1500}, format="json")
    assert r.json()["earnings_goal"] == 1500 and "earnings_today" in r.json()
    bad = api(driver.user).post("/api/v1/driver/earnings-goal/", {"amount": 99999}, format="json")
    assert bad.status_code == 422
