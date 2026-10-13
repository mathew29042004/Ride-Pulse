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

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "ADMIN": Cap.all(),
    "OPS_MANAGER": frozenset(_OPS_MANAGER),
    "SUPPORT_AGENT": frozenset(_SUPPORT_AGENT),
    "DRIVER": frozenset(),
    "RIDER": frozenset(),
}


def capabilities_for(role: str) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(role, frozenset())
