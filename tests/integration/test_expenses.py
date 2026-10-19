"""Expense claims: policy flags, receipts, the 60-day window, duplicates, manager approval (never
your own; reasons for refusals and over-policy approvals), and repayment through payroll."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.workspace import expenses, payroll

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def hire(role, boss=None):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"X{user.pk:05d}",
        title=role.title(),
        department="FLEET",
        state="Kerala",
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )
    payroll.SalaryStructure.objects.create(
        user=user, monthly_gross=Decimal(30_000), effective_from=date(2025, 1, 1)
    )
    return user


def receipt(name="bill.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 receipt")


def approved_claims():
    lead = hire(Role.SUPPORT_LEAD)
    exec_ = hire(Role.FLEET_EXECUTIVE, lead.staff_profile)
    today = timezone.localdate()
    with pytest.raises(BusinessRuleViolation, match="receipt"):
        expenses.submit(
            exec_, category="FUEL", spent_on=today, amount=800, description="Diesel for audit"
        )
    with pytest.raises(BusinessRuleViolation, match="60 days"):
        expenses.submit(
            exec_,
            category="FOOD",
            spent_on=today - timedelta(days=70),
            amount=150,
            description="Lunch",
        )
    fuel = expenses.submit(
        exec_,
        category="FUEL",
        spent_on=today,
        amount=800,
        description="Diesel for audit",
        receipt=receipt(),
    )
    with pytest.raises(BusinessRuleViolation, match="already claimed"):
        expenses.submit(
            exec_,
            category="FUEL",
            spent_on=today,
            amount=800,
            description="Diesel again",
            receipt=receipt(),
        )
    hotel = expenses.submit(
        exec_,
        category="STAY",
        spent_on=today,
        amount=5200,
        description="Hotel, Thrissur hub audit",
        receipt=receipt("hotel.jpg"),
    )
    assert hotel.over_policy and not fuel.over_policy

    with pytest.raises(ActionNotPermitted):
        expenses.decide(fuel, manager=exec_, approve=True)  # not your own
    with pytest.raises(BusinessRuleViolation, match="over the policy"):
        expenses.decide(hotel, manager=lead, approve=True)
    with pytest.raises(BusinessRuleViolation, match="reason"):
        expenses.decide(fuel, manager=lead, approve=False)
    expenses.decide(fuel, manager=lead, approve=True)
    expenses.decide(
        hotel, manager=lead, approve=True, note="Only hotel near the hub during the festival"
    )
    return exec_, lead


def test_repaid_with_the_next_salary(admin):
    exec_, _ = approved_claims()
    month = timezone.localdate().replace(day=1)
    payroll.run(month)
    slip = payroll.Payslip.objects.get(user=exec_)
    assert ["Expense reimbursement", "6000.00"] in slip.earnings
    payroll.run(month)  # re-running the draft keeps the reimbursement
    slip.refresh_from_db()
    assert ["Expense reimbursement", "6000.00"] in slip.earnings
    payroll.approve(month, user=admin)
    payroll.mark_paid(month, user=admin, bank_reference="UTR0001")
    assert set(expenses.ExpenseClaim.objects.values_list("status", flat=True)) == {"PAID"}
    # Not taxed or subject to PF: deductions are the same as without it.
    without = payroll.compute(exec_, month)
    assert without["total_deductions"] == slip.total_deductions


def test_api(api):
    lead = hire(Role.SUPPORT_LEAD)
    exec_ = hire(Role.FLEET_EXECUTIVE, lead.staff_profile)
    made = api(exec_).post(
        "/api/v1/work/expenses/",
        {
            "category": "FOOD",
            "spent_on": str(timezone.localdate()),
            "amount": "150",
            "description": "Lunch at hub",
        },
        format="multipart",
    )
    assert made.status_code == 201
    board = api(lead).get("/api/v1/work/expenses/").json()
    assert board["to_approve"][0]["id"] == made.json()["id"]
    decided = api(lead).post(
        f"/api/v1/work/expenses/{made.json()['id']}/decide/", {"approve": True}, format="json"
    )
    assert decided.json()["status"] == "APPROVED"


def test_rules_and_approval():
    approved_claims()
