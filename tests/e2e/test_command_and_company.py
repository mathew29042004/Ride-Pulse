"""Browser tests for the commander's desk, search, approvals and the company website."""

import re

import pytest

pytest.importorskip("playwright", reason="install requirements/dev.txt for browser tests")
from playwright.sync_api import expect

from apps.accounts.models import Role

from .test_recent_features import sign_in, staff

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]


def test_commander_lands_on_their_desk_and_issues_an_order(page, live_server):
    from apps.chat.services import sync_channels
    from apps.reliability.models import CommandOrder

    staff(Role.COMMANDER, "Vikram", department="LEADERSHIP")
    sync_channels()
    sign_in(page, live_server, _email(Role.COMMANDER))
    expect(page).to_have_url(re.compile(r"/ops/command"))
    expect(page.get_by_text("Commander's desk")).to_be_visible()
    page.get_by_role("button", name="Surge off").click()
    page.get_by_placeholder("e.g. Citywide bandh called for today").fill(
        "Festival evening: keep fares fair"
    )
    page.get_by_role("button", name="Issue order for every city").click()
    expect(page.get_by_role("button", name="Lift")).to_be_visible()
    assert CommandOrder.objects.filter(kind="SURGE_OFF").exists()


def test_search_and_approvals(page, live_server):
    boss = staff(Role.OPS_MANAGER, "Meena", department="OPERATIONS")
    staff(Role.SUPPORT_AGENT, "Ravi", boss=boss.staff_profile)
    sign_in(page, live_server, boss.email)
    page.get_by_role("button", name=re.compile("^Search")).click()
    page.get_by_label("Search everything").fill("Ravi")
    expect(page.get_by_text("Colleague").first).to_be_visible()
    page.keyboard.press("Escape")
    page.goto(f"{live_server.url}/ops/approvals")
    expect(page.get_by_text("You're all caught up")).to_be_visible()


def test_public_careers_application(page, live_server):
    from django.utils import timezone

    from apps.workspace.company import JobApplication, JobOpening

    job = JobOpening.objects.create(
        title="Dispatch Controller",
        department="OPERATIONS",
        summary="Keep riders moving",
        description="Night shift.",
        posted_at=timezone.now(),
    )
    page.goto(f"{live_server.url}/careers")
    page.get_by_text("Dispatch Controller").click()
    expect(page).to_have_url(re.compile(rf"/careers/{job.pk}"))
    page.get_by_label("Full name").fill("Kavin Raj")
    page.get_by_label("Email").fill("kavin@example.com")
    page.get_by_label("Mobile number").fill("9840012345")
    page.get_by_role("button", name="Send application").click()
    expect(page.get_by_text("Thank you for applying!")).to_be_visible()
    assert JobApplication.objects.filter(job=job, email="kavin@example.com").exists()


def _email(role):
    from apps.accounts.models import User

    return User.objects.filter(role=role).latest("pk").email
