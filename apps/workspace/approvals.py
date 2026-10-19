"""One inbox for everything waiting on me: leave, expense claims and attendance corrections from
my team, large refunds (finance), vehicle loans (payouts), job applications (HR) and the chief's
decisions. Each item links to the page where it's decided; the count shows in the console header.
"""

from apps.accounts.roles import Cap


def pending(user) -> list[dict]:
    from apps.drivers.loans import LoanStatus, VehicleLoan
    from apps.reliability.models import DecisionRequest, DecisionStatus

    from .attendance import Attendance, CorrectionStatus
    from .company import JobApplication
    from .expenses import ClaimStatus, ExpenseClaim
    from .models import LeaveRequest, LeaveStatus
    from .powers import RefundApproval
    from .services import team_of

    items: list[dict] = []
    team = team_of(user) - {user.pk}
    if team:
        for r in LeaveRequest.objects.filter(
            user_id__in=team, status=LeaveStatus.PENDING
        ).select_related("user")[:30]:
            items.append(
                {
                    "kind": "Leave",
                    "title": f"{r.user.get_full_name()}: {r.get_kind_display()} leave",
                    "detail": f"{r.starts_on:%d %b} – {r.ends_on:%d %b}. {r.reason}".strip(),
                    "link": "/ops/roster",
                }
            )
        for c in ExpenseClaim.objects.filter(
            user_id__in=team, status=ClaimStatus.SUBMITTED
        ).select_related("user")[:30]:
            items.append(
                {
                    "kind": "Expense",
                    "title": f"{c.user.get_full_name()}: "
                    f"₹{c.amount:,.0f} {c.get_category_display()}",
                    "detail": c.description,
                    "link": "/ops/expenses",
                }
            )
        for a in Attendance.objects.filter(
            user_id__in=team, correction_status=CorrectionStatus.PENDING
        ).select_related("user")[:30]:
            items.append(
                {
                    "kind": "Attendance",
                    "title": f"{a.user.get_full_name()}: correction for {a.day:%d %b}",
                    "detail": a.correction_reason,
                    "link": "/ops/attendance",
                }
            )
    if user.has_capability(Cap.REFUND_APPROVE):
        for r in RefundApproval.objects.filter(status=RefundApproval.PENDING).select_related(
            "trip"
        )[:30]:
            items.append(
                {
                    "kind": "Refund",
                    "title": f"₹{r.amount:,.0f} refund, {r.trip.trip_number}",
                    "detail": r.reason,
                    "link": "/ops/powers",
                }
            )
    if user.has_capability(Cap.PAYOUTS_MANAGE):
        for loan in VehicleLoan.objects.filter(status=LoanStatus.REQUESTED).select_related(
            "driver__user"
        )[:30]:
            items.append(
                {
                    "kind": "Loan",
                    "title": f"{loan.driver.user.get_full_name()}: ₹{loan.principal:,.0f} loan",
                    "detail": loan.get_purpose_display(),
                    "link": "/ops/loans",
                }
            )
    if user.has_capability(Cap.PEOPLE_MANAGE):
        for a in JobApplication.objects.filter(status="NEW").select_related("job")[:30]:
            items.append(
                {
                    "kind": "Application",
                    "title": f"{a.name} for {a.job.title}",
                    "detail": "Referred by a colleague"
                    if a.referred_by_id
                    else "From the careers page",
                    "link": "/ops/company",
                }
            )
    if user.has_capability(Cap.COMMAND):
        for d in DecisionRequest.objects.filter(status=DecisionStatus.PENDING)[:30]:
            items.append(
                {
                    "kind": "Decision",
                    "title": d.title,
                    "detail": d.detail[:160],
                    "link": "/ops/command",
                }
            )
    return items
