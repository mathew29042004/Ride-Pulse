"""The company portal: the public website (about, careers, apply, contact) and the employee
intranet (home, directory, the commander's messages, referrals, HR reviewing applications)."""

from datetime import date

import pytest
from django.utils import timezone

from apps.accounts.models import Department, Role, StaffProfile
from apps.workspace import company

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def _job():
    return company.JobOpening.objects.create(
        title="Dispatch Controller",
        department="OPERATIONS",
        summary="Keep riders moving",
        description="Night shift",
        posted_at=timezone.now(),
    )


def _profile(user, i):
    return StaffProfile.objects.create(
        user=user,
        employee_id=f"P{i}",
        title=user.get_role_display(),
        department=Department.LEADERSHIP,
        joined_on=date(2024, 1, 1),
    )


def test_public_site_and_apply(client):
    job = _job()
    hr = make_staff(Role.HR_MANAGER)
    about = client.get("/api/v1/public/company/").json()
    assert about["jobs"][0]["title"] == "Dispatch Controller" and "numbers" in about
    assert client.get(f"/api/v1/public/company/jobs/{job.pk}/").json()["description"]
    form = {"name": "Kavin", "email": "kavin@example.com", "phone": "98400 12345"}
    assert client.post(f"/api/v1/public/company/jobs/{job.pk}/", form).status_code == 201
    again = client.post(f"/api/v1/public/company/jobs/{job.pk}/", form)
    assert again.status_code == 422  # one application per role
    assert hr.notifications.filter(title__contains="New application").exists()
    sent = client.post(
        "/api/v1/public/company/contact/",
        {"name": "Asha", "email": "asha@example.com", "message": "We'd like 200 rides a month"},
    )
    assert sent.status_code == 201


def test_intranet_directory_messages_and_referrals(api):
    boss = make_staff(Role.COMMANDER)
    hr = make_staff(Role.HR_MANAGER)
    agent = make_staff(Role.SUPPORT_AGENT)
    for i, u in enumerate([boss, hr, agent]):
        _profile(u, i)
    job = _job()
    home = api(agent).get("/api/v1/company/").json()
    assert home["headcount"] == 3 and home["jobs"] and home["holidays"] is not None
    people = api(agent).get(f"/api/v1/company/directory/?q={hr.first_name}").json()["people"]
    assert people and people[0]["id"] == hr.pk
    assert (
        api(agent).post("/api/v1/company/message/", {"title": "x", "body": "y"}).status_code == 403
    )
    r = api(boss).post(
        "/api/v1/company/message/",
        {"title": "Record month", "body": "Thank you all for a record October, team."},
    )
    assert (
        r.status_code == 201 and agent.notifications.filter(title__contains="Record month").exists()
    )
    api(agent).post(
        "/api/v1/company/refer/",
        {"job": job.pk, "name": "My cousin", "email": "c@example.com", "phone": "9840011111"},
        format="json",
    )
    assert api(agent).get("/api/v1/company/applications/").status_code == 403
    apps_ = api(hr).get("/api/v1/company/applications/").json()["applications"]
    assert apps_[0]["referred_by"] == agent.get_full_name()
    api(hr).post(f"/api/v1/company/applications/{apps_[0]['id']}/status/", {"status": "INTERVIEW"})
    assert agent.notifications.filter(title__contains="Your referral").exists()


def test_search_respects_the_role(api, make_driver):
    driver = make_driver(online=False)
    ops = make_staff(Role.OPS_MANAGER)
    hr = make_staff(Role.HR_MANAGER)
    q = driver.user.first_name + " " + driver.user.last_name
    found = api(ops).get(f"/api/v1/search/?q={q}").json()["results"]
    assert any(r["kind"] == "Driver" for r in found)
    assert not any(
        r["kind"] == "Driver" for r in api(hr).get(f"/api/v1/search/?q={q}").json()["results"]
    )


def test_hiring_sets_up_the_new_employee(api, chennai):
    from apps.accounts.models import User
    from apps.chat.models import Message
    from apps.chat.services import sync_channels
    from apps.workspace.models import WorkTask

    hr = make_staff(Role.HR_MANAGER)
    boss = make_staff(Role.OPS_MANAGER)
    _profile(hr, 90)
    bp = _profile(boss, 91)
    bp.city, bp.state = chennai, chennai.state
    bp.save()
    sync_channels()
    job = company.JobOpening.objects.create(
        title="Dispatch Controller",
        department="OPERATIONS",
        city=chennai,
        role="DISPATCH_CONTROLLER",
        summary="x",
        description="y",
        posted_at=timezone.now(),
    )
    a = company.apply(job, name="Kavin Raj", email="kavin@example.com", phone="9840012345")
    api(hr).post(f"/api/v1/company/applications/{a.pk}/status/", {"status": "HIRED"})
    new = User.objects.get(email="kavin@example.com")
    assert new.role == "DISPATCH_CONTROLLER" and not new.has_usable_password()
    assert new.staff_profile.reports_to == bp and new.salary.monthly_gross > 0
    assert WorkTask.objects.filter(assignee=new).count() == 4
    assert Message.objects.filter(body__contains="Please welcome Kavin Raj").exists()
    job.refresh_from_db()
    assert not job.is_open
