"""Recent features in a real browser: team chat, monsoon mode, staff attendance, vehicle loans,
office commute, the NPS survey card and switching the app to Malayalam."""

import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

pytest.importorskip("playwright", reason="install requirements/dev.txt for browser tests")
from playwright.sync_api import expect

from apps.accounts.models import Role, StaffProfile
from apps.riders.services import register_rider

from ..conftest import T_NAGAR, make_staff

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PASSWORD = "e2e-test-pass-2026"
_ids = iter(range(1, 10_000))


def sign_in(page, live_server, email: str) -> None:
    page.goto(f"{live_server.url}/login")
    page.get_by_role("tab", name="Email").click()
    page.get_by_placeholder("you@example.com").fill(email)
    page.get_by_placeholder("••••••••").fill(PASSWORD)
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page).not_to_have_url(re.compile(r"/login"))


def staff(role, first, *, boss=None, department="SUPPORT"):
    user = make_staff(role)
    user.set_password(PASSWORD)
    user.first_name = first
    user.save()
    StaffProfile.objects.create(
        user=user,
        employee_id=f"E2E{next(_ids):04d}",
        title=role.title(),
        department=department,
        state="Tamil Nadu",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    return user


def rider(n, first="Asha"):
    return register_rider(
        email=f"e2e.recent{n}@test.dev",
        password=PASSWORD,
        first_name=first,
        phone=f"98100002{n:02d}",
    )


def test_team_chat_direct_message(page, live_server):
    from apps.chat.models import Message

    me = staff(Role.SUPPORT_AGENT, "Kavya")
    staff(Role.SUPPORT_LEAD, "Ravi")
    sign_in(page, live_server, me.email)
    page.goto(f"{live_server.url}/ops/chat")
    page.get_by_role("button", name="Message").first.click()
    page.get_by_placeholder("Search by name, email or title").fill("Ravi")
    page.get_by_role("button", name=re.compile("Ravi")).click()
    page.get_by_label("Message", exact=True).fill("Can you take the Kochi refund ticket?")
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("Can you take the Kochi refund ticket?")).to_be_visible()
    assert Message.objects.filter(author=me, body__startswith="Can you take").exists()


def test_ops_turns_on_flood_mode_and_bikes_pause(page, live_server, chennai):
    from apps.reliability.models import WeatherAlert
    from apps.rides import services as rides

    manager = staff(Role.OPS_MANAGER, "Meera", department="OPERATIONS")
    sign_in(page, live_server, manager.email)
    page.goto(f"{live_server.url}/ops/weather")
    page.get_by_label("City").select_option(label="Chennai")
    page.get_by_role("button", name="Flooding").click()
    page.get_by_role("button", name="Turn on").click()
    expect(page.get_by_text("Turned on.")).to_be_visible()
    assert WeatherAlert.objects.get(city=chennai).level == "FLOOD"
    options = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=(13.05, 80.2824))
    bike = next(o for o in options["options"] if o["ride_type"].code == "BIKE")
    assert bike["availability"] == "CLOSED"


def test_staff_clock_in_and_out(page, live_server, now):
    from apps.workspace.attendance import Attendance
    from apps.workspace.models import Shift

    agent = staff(Role.SUPPORT_AGENT, "Divya")
    Shift.objects.create(
        user=agent,
        day=now.date(),
        slot="MORNING",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=7),
    )
    sign_in(page, live_server, agent.email)
    page.goto(f"{live_server.url}/ops/attendance")
    page.get_by_role("button", name="Clock in").click()
    expect(page.get_by_text(re.compile("Clocked in at"))).to_be_visible()
    page.get_by_role("button", name="Clock out").click()
    expect(page.get_by_role("button", name="Clock in")).to_be_visible()
    record = Attendance.objects.get(user=agent)
    assert record.clock_in and record.clock_out


def test_driver_applies_for_a_vehicle_loan(page, live_server, make_driver, now, monkeypatch):
    from apps.drivers import loans
    from apps.drivers.models import DriverProfile

    driver = make_driver(online=False)
    driver.user.set_password(PASSWORD)
    driver.user.save()
    DriverProfile.objects.filter(pk=driver.pk).update(
        completed_trips=400, approved_at=now - timedelta(days=200), rating=Decimal("4.8")
    )
    monkeypatch.setattr(loans, "average_weekly_earnings", lambda d, **k: Decimal(12_000))
    sign_in(page, live_server, driver.user.email)
    page.goto(f"{live_server.url}/drive/loan")
    page.get_by_label("What is the loan for?").select_option("SWITCH_TO_EV")
    page.get_by_label("Which vehicle?").fill("Tata Tiago EV")
    page.get_by_role("button", name="2 yr").click()
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_text("Tata Tiago EV · Applied")).to_be_visible()
    loan = loans.VehicleLoan.objects.get(driver=driver)
    assert loan.purpose == "SWITCH_TO_EV" and loan.tenure_weeks == 104


def test_employee_joins_the_office_commute(page, live_server):
    from datetime import time

    from apps.pricing.models import RideType
    from apps.riders import commute, profiles

    owner, employee = rider(1, "Owner"), rider(2, "Anita")
    company = profiles.create_profile(owner, kind="BUSINESS", name="Acme Pvt Ltd")
    invitation = profiles.invite(company, user=owner.user, phone=employee.user.phone)
    profiles.respond(invitation, user=employee.user, accept=True)
    commute.create_plan(
        company,
        rider=owner,
        name="General shift",
        office_name="Acme, Marina",
        office=(13.05, 80.2824),
        ride_type=RideType.objects.get(code="MINI"),
        weekdays=[0, 1, 2, 3, 4],
        arrive_by=time(9, 30),
        leave_at=time(18, 30),
    )
    sign_in(page, live_server, employee.user.email)
    page.goto(f"{live_server.url}/ride/commute")
    page.get_by_role("button", name="Join").click()
    page.get_by_placeholder("Search for your home pick-up").fill("T. Nagar")
    page.get_by_role("button", name=re.compile("T. Nagar")).first.click()
    page.get_by_role("button", name="Join").click()
    expect(page.get_by_text("Leave this plan")).to_be_visible()
    assert commute.CommuteEnrolment.objects.filter(rider=employee).exists()


def test_rider_answers_the_nps_survey(page, live_server, monkeypatch):
    from apps.trust import nps
    from apps.trust.models import NpsResponse

    monkeypatch.setitem(nps.MIN_TRIPS, "RIDER", 0)
    asha = rider(3)
    sign_in(page, live_server, asha.user.email)
    expect(
        page.get_by_text("How likely are you to recommend Ride Pulse to a friend?")
    ).to_be_visible()
    page.get_by_role("button", name="9", exact=True).click()
    page.get_by_placeholder("What do you like most? (optional)").fill("Drivers are polite")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("How likely are you to recommend")).to_have_count(0)
    answer = NpsResponse.objects.get(user=asha.user)
    assert answer.score == 9 and answer.comment == "Drivers are polite"


def test_rider_switches_the_app_to_malayalam(page, live_server):
    asha = rider(4)
    sign_in(page, live_server, asha.user.email)
    page.goto(f"{live_server.url}/ride/account")
    page.get_by_role("radio", name="മലയാളം").click()
    expect(page.get_by_text("സേവ് ചെയ്ത സ്ഥലങ്ങൾ")).to_be_visible()  # "Saved places"
    asha.user.refresh_from_db()
    assert asha.user.language == "ml"  # chat messages now reach them in Malayalam
