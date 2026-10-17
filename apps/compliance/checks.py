"""The compliance dashboard: for each state, every Aggregator Guidelines rule we can check, its
status, and exactly which drivers, vehicles or settings need fixing.

Pricing rules are also *enforced* where the money moves (surge capped per state in
``pricing.current_surge``; cancellation fees capped in ``rides.services``), so these checks show
both the configuration and anything that slipped through before the rules existed.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.conf import platform_commission_percent, surge_max_multiplier
from apps.drivers.models import DriverProfile, OnboardingStatus, Vehicle
from apps.geo.models import City

from .rules import for_state


def _status(bad: int, total: int) -> str:
    if bad == 0:
        return "OK"
    return "ACTION" if bad / max(total, 1) > 0.05 else "WARN"


def state_report(state: str, *, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    law = for_state(state)
    drivers = DriverProfile.objects.filter(
        city__state=state, onboarding_status=OnboardingStatus.APPROVED
    )
    total = drivers.count()
    refresher = today - timedelta(days=30 * int(law["refresher_months"]))
    unverified = (
        drivers.filter(police_verified_on__isnull=True)
        if law["police_verification"]
        else drivers.none()
    )
    untrained = (
        drivers.filter(Q(induction_trained_on__isnull=True) | Q(induction_trained_on__lt=refresher))
        if law["induction_training"]
        else drivers.none()
    )
    oldest_year = today.year - int(law["vehicle_max_age_years"])
    vehicles = Vehicle.objects.filter(is_active=True, driver__city__state=state)
    old_vehicles = vehicles.filter(year__lt=oldest_year)
    from apps.pricing.models import FareRule

    cities = City.objects.filter(state=state)
    fee_cap = Decimal(str(law["cancellation_fee_max"]))
    high_fees = FareRule.objects.filter(
        city__in=cities, is_active=True, cancellation_fee__gt=fee_cap
    )
    driver_share = Decimal(100) - platform_commission_percent()
    configured_surge = surge_max_multiplier()
    surge_cap = Decimal(str(law["surge_cap"]))
    checks = [
        {
            "key": "surge_cap",
            "rule": f"Surge at most {surge_cap}x the base fare",
            "status": "OK",
            "detail": f"Enforced per state: fares never go above {surge_cap}x here "
            f"(the platform setting allows {configured_surge}x elsewhere).",
        },
        {
            "key": "driver_share",
            "rule": f"Drivers keep at least {law['driver_share_min_percent']}% of the fare",
            "status": "OK"
            if driver_share >= Decimal(str(law["driver_share_min_percent"]))
            else "ACTION",
            "detail": f"Commission is {platform_commission_percent()}%: "
            f"drivers keep {driver_share}%.",
        },
        {
            "key": "cancellation_fee",
            "rule": f"Cancellation fee at most {law['cancellation_fee_percent']}% of the fare, "
            f"up to ₹{fee_cap}",
            "status": "OK",
            "detail": "Enforced when a fee is charged."
            + (
                f" {high_fees.count()} fare rules list a higher fee (capped when charged)."
                if high_fees.exists()
                else ""
            ),
        },
        {
            "key": "police_verification",
            "rule": "Police verification before the first ride",
            "status": _status(unverified.count(), total),
            "detail": f"{unverified.count()} of {total} approved drivers not verified "
            "(they can't go online).",
            "fix": "drivers",
        },
        {
            "key": "induction_training",
            "rule": f"Induction training, refreshed every {law['refresher_months']} months",
            "status": _status(untrained.count(), total),
            "detail": f"{untrained.count()} of {total} approved drivers need training "
            "or a refresher.",
            "fix": "drivers",
        },
        {
            "key": "vehicle_age",
            "rule": f"Vehicles at most {law['vehicle_max_age_years']} years old",
            "status": _status(old_vehicles.count(), vehicles.count()),
            "detail": f"{old_vehicles.count()} of {vehicles.count()} active vehicles are "
            f"from before {oldest_year}.",
            "fix": "vehicles",
        },
        {
            "key": "driver_insurance",
            "rule": f"Driver health cover ₹{law['health_cover']:,} "
            f"and term cover ₹{law['term_cover']:,}",
            "status": "OK",
            "detail": "Group policy for every active driver (see Trust → insurance claims).",
        },
        {
            "key": "safety_features",
            "rule": "Panic button, live tracking and a 24×7 control room",
            "status": "OK",
            "detail": "SOS in the app, live trip sharing, Ride Check and the Safety desk.",
        },
    ]
    return {
        "state": state,
        "drivers": total,
        "checks": checks,
        "ok": sum(c["status"] == "OK" for c in checks),
        "unverified": [_driver_row(d) for d in unverified.select_related("user", "city")[:100]],
        "untrained": [_driver_row(d) for d in untrained.select_related("user", "city")[:100]],
        "old_vehicles": [
            {
                "id": v.pk,
                "registration": v.registration_number,
                "name": f"{v.make} {v.model}",
                "year": v.year,
                "driver": v.driver.name,
            }
            for v in old_vehicles.select_related("driver__user")[:100]
        ],
    }


def _driver_row(driver: DriverProfile) -> dict:
    return {
        "id": driver.pk,
        "name": driver.name,
        "city": driver.city.name if driver.city_id else "",
        "police_verified_on": driver.police_verified_on,
        "induction_trained_on": driver.induction_trained_on,
    }


def overview() -> list[dict]:
    states = sorted(set(City.objects.filter(is_active=True).values_list("state", flat=True)))
    rows = []
    for state in states:
        report = state_report(state)
        rows.append(
            {
                "state": state,
                "drivers": report["drivers"],
                "ok": report["ok"],
                "total": len(report["checks"]),
                "actions": [c["rule"] for c in report["checks"] if c["status"] != "OK"],
            }
        )
    return rows


def record_police_verification(driver: DriverProfile, *, reference: str, user, on=None):
    reference = reference.strip()[:40]
    if len(reference) < 4:
        from apps.core.exceptions import BusinessRuleViolation

        raise BusinessRuleViolation(
            "Enter the police verification certificate number.", field="reference"
        )
    DriverProfile.objects.filter(pk=driver.pk).update(
        police_verified_on=on or timezone.localdate(), police_verification_ref=reference
    )
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    notify(
        driver.user,
        "Police verification confirmed",
        "Thanks! One step closer to your first ride.",
        level=Level.SUCCESS,
        link="/drive",
    )
    driver.refresh_from_db()
    return driver


def record_induction(driver: DriverProfile, *, on=None) -> DriverProfile:
    DriverProfile.objects.filter(pk=driver.pk).update(
        induction_trained_on=on or timezone.localdate()
    )
    driver.refresh_from_db()
    return driver
