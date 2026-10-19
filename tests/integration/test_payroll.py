"""Payroll: the new-regime tax maths, salary split, loss of pay for absences (leave is paid),
overtime and night allowance, PF/ESI/professional tax, and the run → approve → pay flow with
payslip PDFs that only the employee (or HR) can open."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.geo.models import City
from apps.workspace import payroll
from apps.workspace.attendance import Attendance
from apps.workspace.models import Shift

from ..conftest import make_staff

pytestmark = pytest.mark.django_db
MONTH = date(2026, 3, 1)


def at(day, h, m=0):
    return timezone.make_aware(datetime.combine(date(2026, 3, day), time(h, m)))


def hire(role, gross, *, city="chennai", state="Tamil Nadu"):
    user = make_staff(role)
    StaffProfile.objects.create(
        user=user,
        employee_id=f"P{user.pk:05d}",
        title=role.title(),
        department="SUPPORT",
        state=state,
        city=City.objects.get(slug=city),
        joined_on=date(2025, 1, 1),
    )
    payroll.SalaryStructure.objects.create(
        user=user, monthly_gross=Decimal(gross), effective_from=date(2025, 1, 1)
    )
    return user


def test_new_regime_tax():
    assert payroll.annual_tax(Decimal(1_200_000)) == 0  # 11.25 L taxable: rebate
    assert payroll.annual_tax(Decimal(1_275_000)) == 0  # exactly 12 L taxable after deduction
    # 18 L gross → 17.25 L taxable: 20k + 40k + 60k + 25% of… no: 4-8 5%, 8-12 10%, 12-16 15%, 16-17.25 20%
    expected = (Decimal(20_000) + 40_000 + 60_000 + Decimal(125_000) * Decimal("0.20")) * Decimal(
        "1.04"
    )
    assert payroll.annual_tax(Decimal(1_800_000)) == expected.quantize(Decimal("0.01"))


def test_payslip_with_absence_overtime_and_night_shifts():
    agent = hire(Role.SUPPORT_AGENT, 20_000)
    # One absent day, one half day, a night shift worked 1 hour over.
    Attendance.objects.create(
        user=agent,
        day=date(2026, 3, 3),
        expected_start=at(3, 9),
        expected_end=at(3, 18),
        status="ABSENT",
    )
    Attendance.objects.create(
        user=agent,
        day=date(2026, 3, 4),
        expected_start=at(4, 9),
        expected_end=at(4, 18),
        clock_in=at(4, 9),
        clock_out=at(4, 12),
        status="HALF_DAY",
        worked_minutes=180,
    )
    night = Shift.objects.create(
        user=agent,
        day=date(2026, 3, 5),
        slot="NIGHT",
        starts_at=at(5, 22),
        ends_at=at(5, 22) + timedelta(hours=8),
    )
    Attendance.objects.create(
        user=agent,
        day=date(2026, 3, 5),
        shift=night,
        expected_start=night.starts_at,
        expected_end=night.ends_at,
        clock_in=night.starts_at,
        clock_out=night.ends_at + timedelta(hours=1),
        status="PRESENT",
        worked_minutes=540,
    )
    f = payroll.compute(agent, MONTH)
    assert f["lop_days"] == Decimal("1.5") and f["paid_days"] == Decimal("29.5")
    labels = dict(f["earnings"])
    # Chennai is a metro: HRA is 50% of basic. Basic is half the gross, scaled by 29.5/31.
    assert labels["Basic"] == Decimal("9516.13") and labels["House rent allowance"] == Decimal(
        "4758.06"
    )
    assert labels["Night shift allowance (1)"] == 200
    assert any(k.startswith("Overtime (1 h 0 min)") for k in labels)
    deductions = dict(f["deductions"])
    assert deductions["Provident fund (12% of basic)"] == Decimal("1141.94")
    assert deductions["ESI (0.75%)"] > 0  # gross ≤ ₹21,000
    assert deductions["Professional tax"] == 100  # Tamil Nadu, under ₹21,000
    assert "Income tax (TDS, new regime)" not in deductions  # ₹2.4 L a year: no tax
    assert f["net"] == f["gross"] - f["total_deductions"]


def test_pf_cap_karnataka_pt_and_tds_for_a_manager():
    manager = hire(Role.OPS_MANAGER, 150_000, city="bengaluru", state="Karnataka")
    f = payroll.compute(manager, MONTH)
    d = dict(f["deductions"])
    assert d["Provident fund (12% of basic)"] == Decimal("1800.00")  # basic capped at ₹15,000
    assert "ESI (0.75%)" not in d and d["Professional tax"] == 200
    assert d["Income tax (TDS, new regime)"] == (
        payroll.annual_tax(Decimal(1_800_000)) / 12
    ).quantize(Decimal("0.01"))


def test_run_approve_pay_and_payslip_access(api, admin):
    agent, other = hire(Role.SUPPORT_AGENT, 25_000), hire(Role.SUPPORT_AGENT, 25_000)
    with pytest.raises(BusinessRuleViolation, match="future"):
        payroll.run(date(2099, 1, 1))
    assert payroll.run(MONTH)["created"] == 2
    with pytest.raises(InvalidStateTransition):
        payroll.mark_paid(MONTH, user=admin, bank_reference="UTR123456")
    payroll.approve(MONTH, user=admin)
    assert payroll.run(MONTH)["kept"] == 2  # approved payslips aren't recalculated
    assert payroll.mark_paid(MONTH, user=admin, bank_reference="UTR123456") == 2
    slip = payroll.Payslip.objects.get(user=agent)
    assert slip.status == "PAID" and payroll.render_pdf(slip).startswith(b"%PDF")

    mine = api(agent).get("/api/v1/work/payslips/").json()
    assert Decimal(str(mine["payslips"][0]["net"])) == slip.net
    assert api(agent).get(f"/api/v1/work/payslips/{slip.pk}/pdf/").status_code == 200
    assert api(other).get(f"/api/v1/work/payslips/{slip.pk}/pdf/").status_code == 403
    assert api(agent).get("/api/v1/work/payroll/").status_code == 403
    board = api(admin).get("/api/v1/work/payroll/?month=2026-03-01").json()
    assert board["people"] == 2 and Decimal(str(board["cost_to_company"])) > Decimal(
        str(board["gross"])
    )
