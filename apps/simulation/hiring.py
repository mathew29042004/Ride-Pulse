"""A hiring round: the specialist teams in every state and more people in every existing role.

Per state (reporting to the regional manager): a finance manager, an HR manager, a compliance
officer, a pricing analyst and a second associate manager for each line of business. Per busy
city (the eight with the most drivers): a safety officer, two dispatch controllers, a deputy city
operations manager, three more support agents and two more fleet executives. Plus a second
administrator who reports to the commander. Tamil Nadu's specialists get demo logins.
"""

from django.db.models import Count

from apps.accounts.models import Department, Role, StaffProfile

STATE_TEAM = [
    (Role.FINANCE_MANAGER, Department.FINANCE, "Finance Manager"),
    (Role.HR_MANAGER, Department.PEOPLE, "HR Manager"),
    (Role.COMPLIANCE_OFFICER, Department.LEGAL, "Compliance Officer"),
    (Role.PRICING_ANALYST, Department.RIDES, "Pricing Analyst"),
]
SECOND_ASSOCIATES = [
    (Role.ASSOC_RIDES, Department.RIDES, "Senior Associate, Rides"),
    (Role.ASSOC_SUPPORT, Department.SUPPORT, "Senior Associate, Customer Support"),
    (Role.ASSOC_MAINTENANCE, Department.MAINTENANCE, "Senior Associate, Fleet & Maintenance"),
    (Role.ASSOC_INTERCITY, Department.INTERCITY, "Senior Associate, Intercity & Rentals"),
    (Role.ASSOC_PARCELS, Department.PARCELS, "Senior Associate, Parcels"),
]
DEMO = {
    Role.FINANCE_MANAGER: ("finance@ridepulse.dev", "Revathi", "Sundaram"),
    Role.HR_MANAGER: ("hr@ridepulse.dev", "Deepa", "Natarajan"),
    Role.COMPLIANCE_OFFICER: ("compliance@ridepulse.dev", "Harish", "Chandran"),
    Role.PRICING_ANALYST: ("pricing@ridepulse.dev", "Aravind", "Raghavan"),
    Role.SAFETY_OFFICER: ("safety@ridepulse.dev", "Kavya", "Selvam"),
    Role.DISPATCH_CONTROLLER: ("dispatch@ridepulse.dev", "Manoj", "Pandian"),
}
BUSY_CITIES = 8


def hire(*, seed: int = 11, log=print) -> dict:
    from apps.geo.models import City
    from apps.simulation.network import NetworkBuilder

    if StaffProfile.objects.filter(user__role=Role.FINANCE_MANAGER).exists():
        return {"hired": 0}
    nb = NetworkBuilder(seed=seed, log=log)
    nb.next_employee = StaffProfile.objects.count() + 1
    nb.seeder.used_emails |= set(StaffProfile.objects.values_list("user__email", flat=True))
    before = StaffProfile.objects.count()

    def demo_for(role, state):
        return DEMO.get(role, (None, None, None)) if state == "Tamil Nadu" else (None, None, None)

    for regional in StaffProfile.objects.filter(user__role=Role.REGIONAL_MANAGER).select_related(
        "city"
    ):
        state = regional.state
        for role, dept, title in STATE_TEAM:
            email, first, last = demo_for(role, state)
            nb._employee(
                role,
                dept,
                f"{title} ({state})",
                city=regional.city,
                state=state,
                reports_to=regional,
                email=email,
                first=first,
                last=last,
            )
        for role, dept, title in SECOND_ASSOCIATES:
            nb._employee(
                role,
                dept,
                f"{title} ({state})",
                city=regional.city,
                state=state,
                reports_to=regional,
            )

    busy = (
        City.objects.filter(is_active=True)
        .annotate(n=Count("drivers"))
        .order_by("-n")[:BUSY_CITIES]
    )
    for city in busy:
        manager = StaffProfile.objects.filter(city=city, user__role=Role.OPS_MANAGER).first()
        if manager is None:
            continue
        lead = (
            StaffProfile.objects.filter(city=city, user__role=Role.SUPPORT_LEAD).first() or manager
        )
        execs_lead = manager
        for role, dept, title, boss, n in [
            (Role.SAFETY_OFFICER, Department.SAFETY, "Safety Officer", manager, 1),
            (Role.DISPATCH_CONTROLLER, Department.OPERATIONS, "Dispatch Controller", manager, 2),
            (Role.OPS_MANAGER, Department.OPERATIONS, "Deputy City Operations Manager", manager, 1),
            (Role.SUPPORT_AGENT, Department.SUPPORT, "Customer Support Agent", lead, 3),
            (Role.FLEET_EXECUTIVE, Department.MAINTENANCE, "Fleet Executive", execs_lead, 2),
        ]:
            for i in range(n):
                email, first, last = (
                    demo_for(role, city.state) if city.slug == "chennai" and i == 0 else (None,) * 3
                )
                nb._employee(
                    role,
                    dept,
                    f"{title}, {city.name}",
                    city=city,
                    state=city.state,
                    reports_to=boss,
                    email=email,
                    first=first,
                    last=last,
                )

    commander = StaffProfile.objects.filter(user__role=Role.COMMANDER).first()
    nb._employee(
        Role.ADMIN,
        Department.LEADERSHIP,
        "Platform Administrator",
        city=None,
        state="",
        reports_to=commander,
    )
    from apps.chat.services import sync_channels
    from apps.workspace import payroll

    sync_channels()
    payroll.salaries_for_new_staff()
    hired = StaffProfile.objects.count() - before
    log(f"  hiring round: {hired} new employees")
    return {"hired": hired}
