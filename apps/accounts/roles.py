"""Capability-based RBAC for staff.

Views ask "can this user do X?" rather than "is this user an ops manager?", so a role's powers
can change in one place without touching any view. Riders and drivers have no capabilities;
they use self-service endpoints scoped to their own records.
"""


class Cap:
    USERS_MANAGE = "users.manage"
    RIDERS_VIEW = "riders.view"
    RIDERS_MANAGE = "riders.manage"
    DRIVERS_VIEW = "drivers.view"
    DRIVERS_VERIFY = "drivers.verify"
    DRIVERS_MANAGE = "drivers.manage"
    TRIPS_VIEW = "trips.view"
    TRIPS_MANAGE = "trips.manage"
    DISPATCH_RUN = "dispatch.run"
    PRICING_VIEW = "pricing.view"
    PRICING_MANAGE = "pricing.manage"
    PROMOS_MANAGE = "promos.manage"
    PAYMENTS_VIEW = "payments.view"
    PAYMENTS_REFUND = "payments.refund"
    PAYOUTS_MANAGE = "payouts.manage"
    SUPPORT_VIEW = "support.view"
    SUPPORT_MANAGE = "support.manage"
    SAFETY_MANAGE = "safety.manage"
    REPORTS_VIEW = "reports.view"
    AUDIT_VIEW = "audit.view"
    TEAM_VIEW = "team.view"
    FRAUD_REVIEW = "fraud.review"  # review fraud cases, suspend or block
    WORK_USE = "work.use"  # tasks, meetings and check-ins (every employee)
    FLEET_OWN = "fleet.own"  # a fleet owner's own drivers, vehicles and earnings
    FLEET_MANAGE = "fleet.manage"  # ops: fleet owners, quests, vehicle upkeep, airport queue
    PRIVACY_MANAGE = "privacy.manage"  # data requests (DPDP), appeals, insurance claims
    EXPERIMENTS_MANAGE = "experiments.manage"  # feature flags and A/B tests
    TOURS_MANAGE = "tours.manage"  # tour packages, their prices and tour bookings
    ANNOUNCE = "announce"  # announcements to drivers, riders or staff
    PAYROLL_MANAGE = "payroll.manage"  # salaries, the monthly payroll run and payslips (HR)
    COMMAND = "command"  # the commander: standing orders across every city, the command centre
    COUNTER_OPERATE = "counter.operate"  # book rides for walk-up passengers at a station counter

    @classmethod
    def all(cls) -> frozenset[str]:
        return frozenset(v for k, v in vars(cls).items() if k.isupper() and isinstance(v, str))


_OPS_MANAGER = {
    Cap.RIDERS_VIEW,
    Cap.RIDERS_MANAGE,
    Cap.DRIVERS_VIEW,
    Cap.DRIVERS_VERIFY,
    Cap.DRIVERS_MANAGE,
    Cap.TRIPS_VIEW,
    Cap.TRIPS_MANAGE,
    Cap.DISPATCH_RUN,
    Cap.PRICING_VIEW,
    Cap.PRICING_MANAGE,
    Cap.PROMOS_MANAGE,
    Cap.PAYMENTS_VIEW,
    Cap.PAYOUTS_MANAGE,
    Cap.SUPPORT_VIEW,
    Cap.SAFETY_MANAGE,
    Cap.REPORTS_VIEW,
}

_SUPPORT_AGENT = {
    Cap.COUNTER_OPERATE,
    Cap.RIDERS_VIEW,
    Cap.DRIVERS_VIEW,
    Cap.TRIPS_VIEW,
    Cap.PRICING_VIEW,
    Cap.PAYMENTS_VIEW,
    Cap.PAYMENTS_REFUND,
    Cap.SUPPORT_VIEW,
    Cap.SUPPORT_MANAGE,
    Cap.SAFETY_MANAGE,
}

_MANAGERS = {
    *_OPS_MANAGER,
    Cap.TEAM_VIEW,
    Cap.FRAUD_REVIEW,
    Cap.FLEET_MANAGE,
    Cap.PRIVACY_MANAGE,
    Cap.EXPERIMENTS_MANAGE,
    Cap.TOURS_MANAGE,
    Cap.ANNOUNCE,
}

# Associate managers: each runs one line of the business across their state.
_ASSOC_RIDES = {
    Cap.FRAUD_REVIEW,
    Cap.TRIPS_VIEW,
    Cap.TRIPS_MANAGE,
    Cap.DISPATCH_RUN,
    Cap.DRIVERS_VIEW,
    Cap.RIDERS_VIEW,
    Cap.PRICING_VIEW,
    Cap.SAFETY_MANAGE,
    Cap.SUPPORT_VIEW,
    Cap.REPORTS_VIEW,
    Cap.TEAM_VIEW,
}
_ASSOC_SUPPORT = {*_SUPPORT_AGENT, Cap.REPORTS_VIEW, Cap.TEAM_VIEW, Cap.PRIVACY_MANAGE}
_ASSOC_MAINTENANCE = {
    Cap.FLEET_MANAGE,
    Cap.DRIVERS_VIEW,
    Cap.DRIVERS_VERIFY,
    Cap.DRIVERS_MANAGE,
    Cap.TRIPS_VIEW,
    Cap.SAFETY_MANAGE,
    Cap.REPORTS_VIEW,
    Cap.TEAM_VIEW,
}
_ASSOC_INTERCITY = {
    Cap.TOURS_MANAGE,
    Cap.TRIPS_VIEW,
    Cap.TRIPS_MANAGE,
    Cap.DRIVERS_VIEW,
    Cap.PRICING_VIEW,
    Cap.PRICING_MANAGE,
    Cap.SUPPORT_VIEW,
    Cap.REPORTS_VIEW,
    Cap.TEAM_VIEW,
}
_ASSOC_PARCELS = {
    Cap.TRIPS_VIEW,
    Cap.TRIPS_MANAGE,
    Cap.DRIVERS_VIEW,
    Cap.RIDERS_VIEW,
    Cap.SUPPORT_VIEW,
    Cap.SUPPORT_MANAGE,
    Cap.REPORTS_VIEW,
    Cap.TEAM_VIEW,
}
_SUPPORT_LEAD = {*_SUPPORT_AGENT, Cap.TEAM_VIEW, Cap.PRIVACY_MANAGE}
_FLEET_EXECUTIVE = {Cap.DRIVERS_VIEW, Cap.DRIVERS_VERIFY, Cap.TRIPS_VIEW, Cap.FLEET_MANAGE}

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "COMMANDER": Cap.all(),
    "ADMIN": Cap.all() - {Cap.COMMAND},
    "REGIONAL_MANAGER": frozenset({*_MANAGERS, Cap.PAYMENTS_REFUND, Cap.AUDIT_VIEW}),
    "OPS_MANAGER": frozenset(_MANAGERS),
    "ASSOC_RIDES": frozenset(_ASSOC_RIDES),
    "ASSOC_SUPPORT": frozenset(_ASSOC_SUPPORT),
    "ASSOC_MAINTENANCE": frozenset(_ASSOC_MAINTENANCE),
    "ASSOC_INTERCITY": frozenset(_ASSOC_INTERCITY),
    "ASSOC_PARCELS": frozenset(_ASSOC_PARCELS),
    "SUPPORT_LEAD": frozenset(_SUPPORT_LEAD),
    "SUPPORT_AGENT": frozenset(_SUPPORT_AGENT),
    "FLEET_EXECUTIVE": frozenset(_FLEET_EXECUTIVE),
    "DRIVER": frozenset(),
    "RIDER": frozenset(),
    "FLEET_OWNER": frozenset({Cap.FLEET_OWN}),
}


# Every employee uses the workspace; who they can assign work to follows the org chart.
ROLE_CAPABILITIES = {
    role: frozenset(caps | {Cap.WORK_USE})
    if role not in ("DRIVER", "RIDER", "FLEET_OWNER")
    else caps
    for role, caps in ROLE_CAPABILITIES.items()
}


def capabilities_for(role: str) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(role, frozenset())
