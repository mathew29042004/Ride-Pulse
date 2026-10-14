"""The organisation chart: who reports to whom, from leadership down to the fleet executives
who look after driver partners."""

from django.db.models import Count

from .models import StaffProfile


def _node(profile: StaffProfile, children: dict, drivers: dict) -> dict:
    user = profile.user
    return {
        "id": profile.pk,
        "employee_id": profile.employee_id,
        "name": user.get_full_name(),
        "email": user.email,
        "role": user.role,
        "role_label": user.get_role_display(),
        "title": profile.title,
        "department": profile.department,
        "department_label": profile.get_department_display(),
        "state": profile.state,
        "city": profile.city.name if profile.city else "",
        "drivers": drivers.get(profile.pk, 0),
        "reports": [_node(child, children, drivers) for child in children.get(profile.pk, [])],
    }


def tree(*, state: str | None = None) -> list[dict]:
    """Nested org chart; ``state`` keeps leadership plus that state's people."""
    staff = list(
        StaffProfile.objects.select_related("user", "city").order_by("department", "employee_id")
    )
    drivers = dict(
        StaffProfile.objects.annotate(n=Count("drivers")).filter(n__gt=0).values_list("pk", "n")
    )
    if state:
        staff = [s for s in staff if s.state in ("", state)]
    present = {s.pk for s in staff}
    children: dict[int, list[StaffProfile]] = {}
    roots = []
    for profile in staff:
        if profile.reports_to_id in present:
            children.setdefault(profile.reports_to_id, []).append(profile)
        else:
            roots.append(profile)
    return [_node(root, children, drivers) for root in roots]


def summary() -> dict:
    """Headcount by role, department and state (drivers counted as partners)."""
    from apps.drivers.models import DriverProfile, OnboardingStatus

    by_role = dict(
        StaffProfile.objects.values_list("user__role")
        .annotate(n=Count("id"))
        .values_list("user__role", "n")
    )
    by_department = dict(
        StaffProfile.objects.values_list("department")
        .annotate(n=Count("id"))
        .values_list("department", "n")
    )
    by_state = dict(
        StaffProfile.objects.exclude(state="")
        .values_list("state")
        .annotate(n=Count("id"))
        .values_list("state", "n")
    )
    return {
        "employees": StaffProfile.objects.count(),
        "driver_partners": DriverProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED
        ).count(),
        "by_role": by_role,
        "by_department": by_department,
        "by_state": by_state,
    }
