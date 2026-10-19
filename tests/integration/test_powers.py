"""The specialist roles' powers: finance approves big refunds, safety bans for good, dispatch
hands a trip to a chosen driver, compliance freezes erasure, HR moves people."""

from decimal import Decimal

import pytest

from apps.accounts.models import Department, Role, StaffProfile
from apps.core.exceptions import BusinessRuleViolation
from apps.rides.models import Trip
from apps.support import services as support
from apps.support.models import TicketCategory
from apps.trust import privacy
from apps.workspace import powers

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db


def test_big_refunds_wait_for_finance(api, rider, mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    Trip.objects.filter(pk=trip.pk).update(fare_total=Decimal(5000))
    trip.refresh_from_db()
    agent = make_staff(Role.SUPPORT_AGENT)
    lead = make_staff(Role.REGIONAL_MANAGER)  # can refund, but not above the limit
    finance = make_staff(Role.FINANCE_MANAGER)
    ticket = support.open_ticket(
        user=rider.user,
        category=TicketCategory.FARE_DISPUTE,
        subject="Charged twice",
        description="Charged twice for one ride",
        trip=trip,
    )
    support.resolve(ticket, actor=lead, resolution="Refund the whole fare", refund_amount="3000")
    approval = powers.RefundApproval.objects.get()
    assert approval.status == "PENDING" and approval.amount == 3000
    assert finance.notifications.filter(title__contains="needs your approval").exists()
    assert api(agent).get("/api/v1/ops/powers/").status_code == 403
    r = api(finance).post(
        f"/api/v1/ops/powers/refunds/{approval.pk}/decide/", {"approve": True}, format="json"
    )
    assert r.json() == {"status": "APPROVED"}
    assert rider.user.notifications.filter(title__contains="refunded").exists()


def test_a_ban_stops_signing_up_again(api, make_driver):
    from apps.drivers import services as drivers

    safety = make_staff(Role.SAFETY_OFFICER)
    driver = make_driver(online=False)
    with pytest.raises(BusinessRuleViolation):
        powers.ban(driver.user, actor=safety, reason="short")
    r = api(safety).post(
        "/api/v1/ops/powers/ban/",
        {"user": driver.user.pk, "reason": "Assaulted a rider, police case filed"},
        format="json",
    )
    assert r.json()["banned"] == 2  # phone and licence
    driver.refresh_from_db()
    assert driver.onboarding_status == "SUSPENDED"
    with pytest.raises(BusinessRuleViolation, match="can't accept"):
        drivers.register_driver(
            email="new@test.dev",
            password="pw-12345!",
            first_name="Same",
            phone="9000000001",
            city=driver.city,
            license_number=driver.license_number,
            license_expiry=driver.license_expiry,
        )
    powers.lift_ban(driver.user, actor=safety, reason="Acquitted")
    assert not powers.banned(licence=driver.license_number)


def test_dispatch_hands_a_trip_to_a_chosen_driver(api, rider, mini, make_driver, now):
    first = make_driver()
    chosen = make_driver()
    trip = book(rider, mini, now=now)
    offered = pending_offer(trip).driver
    pick = chosen if offered == first else first
    controller = make_staff(Role.DISPATCH_CONTROLLER)
    listed = api(controller).get(f"/api/v1/ops/powers/trips/{trip.pk}/drivers/").json()
    assert pick.pk in [d["id"] for d in listed["drivers"]]
    r = api(controller).post(
        "/api/v1/ops/powers/assign/", {"trip": trip.pk, "driver": pick.pk}, format="json"
    )
    assert r.status_code == 200
    assert pending_offer(trip).driver == pick


def test_legal_hold_blocks_erasure():
    compliance = make_staff(Role.COMPLIANCE_OFFICER)
    rider = make_rider()
    assert not privacy.erasure_blockers(rider.user)
    hold = powers.place_hold(
        rider.user, actor=compliance, case_reference="FIR 221/2026", reason="Police investigation"
    )
    assert any("legal hold" in p for p in privacy.erasure_blockers(rider.user))
    powers.release_hold(hold, actor=compliance)
    assert not privacy.erasure_blockers(rider.user)


def test_hr_moves_people_but_not_into_top_roles(api):
    hr = make_staff(Role.HR_MANAGER)
    boss = make_staff(Role.OPS_MANAGER)
    agent = make_staff(Role.SUPPORT_AGENT)
    for i, u in enumerate([boss, agent]):
        StaffProfile.objects.create(
            user=u,
            employee_id=f"T{i}",
            title="x",
            department=Department.SUPPORT,
            joined_on="2024-01-01",
        )
    r = api(hr).post(
        "/api/v1/ops/powers/transfer/",
        {
            "employee": agent.pk,
            "manager": boss.staff_profile.pk,
            "role": "SUPPORT_LEAD",
            "reason": "Promoted after appraisal",
        },
        format="json",
    )
    assert r.status_code == 200
    agent.refresh_from_db()
    assert agent.role == "SUPPORT_LEAD" and agent.staff_profile.reports_to == boss.staff_profile
    with pytest.raises(BusinessRuleViolation):
        powers.transfer(agent, actor=hr, role="ADMIN", reason="Nope, not allowed")
    with pytest.raises(BusinessRuleViolation, match="loop"):
        powers.transfer(boss, actor=hr, manager=agent.staff_profile, reason="Would be a loop")


def test_a_ban_can_be_undone_within_ten_minutes(api, make_driver):
    from datetime import timedelta

    from django.utils import timezone

    safety = make_staff(Role.SAFETY_OFFICER)
    driver = make_driver(online=False)
    powers.ban(driver.user, actor=safety, reason="Wrong person, reported by mistake")
    r = api(safety).post("/api/v1/ops/powers/undo-ban/", {"user": driver.user.pk}, format="json")
    assert r.json()["undone"] == 2
    driver.refresh_from_db()
    assert driver.onboarding_status != "SUSPENDED" and not powers.banned(
        licence=driver.license_number
    )
    other = make_driver(online=False)
    powers.ban(other.user, actor=safety, reason="Repeated harassment complaints")
    with pytest.raises(BusinessRuleViolation, match="10 minutes"):
        powers.undo_ban(other.user, actor=safety, now=timezone.now() + timedelta(minutes=11))
