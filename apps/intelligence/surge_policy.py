"""Surge optimiser: replay recorded demand and supply under different surge settings and
estimate which one completes the most trips (and earns the most), before testing it live.

Each ``SurgeSnapshot`` is a zone at a moment: open requests (demand) and free drivers (supply).
For a candidate policy (elasticity = how fast price climbs with the demand/supply ratio, and a
cap), we replay every snapshot through a simple, stated market model:

* **Riders** see the multiplier; the share who still book falls as it rises
  (``book = 1 - min(0.6, (m - 1) x 0.5)``, the same response the simulator's riders have).
* **Drivers** come towards surge: supply grows by 25% per 1.0x of surge, within the hour.
* **Completed trips** in the snapshot are min(booked demand, supply x 2 trips per driver-hour
  slot); revenue is completed x average fare x multiplier.

The result ranks policies and recommends one, with the honest caveat that this is a model of
the market, not the market: the next step is an A/B test (``propose_experiment``), never a
silent switch.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import product

from django.db.models import Avg
from django.utils import timezone

from apps.pricing import surge
from apps.pricing.models import SurgeSnapshot

ELASTICITIES = [Decimal("0.3"), Decimal("0.45"), Decimal("0.6"), Decimal("0.8"), Decimal("1.0")]
CAPS = [Decimal("1.5"), Decimal("2.0"), Decimal("2.5"), Decimal("3.0")]
SUPPLY_RESPONSE = 0.25  # +25% drivers per 1.0x of surge
TRIPS_PER_DRIVER = 2.0


def _multiplier(demand: int, supply: int, elasticity: Decimal, cap: Decimal) -> float:
    if demand <= 0:
        return 1.0
    ratio = Decimal(demand) / Decimal(max(supply, 0.5))
    if ratio <= 1:
        return 1.0
    raw = min(Decimal(1) + (ratio - 1) * elasticity, cap)
    return float(surge.to_step(raw, cap=cap))


def book_share(multiplier: float) -> float:
    return 1 - min(0.6, max(0.0, multiplier - 1) * 0.5)


def evaluate(
    snapshots: list[tuple[int, int]], elasticity: Decimal, cap: Decimal, avg_fare: float
) -> dict:
    completed = revenue = lost = 0.0
    surge_snapshots = 0
    for demand, supply in snapshots:
        m = _multiplier(demand, supply, elasticity, cap)
        surge_snapshots += m > 1
        booked = demand * book_share(m)
        drivers = supply * (1 + SUPPLY_RESPONSE * (m - 1))
        done = min(booked, drivers * TRIPS_PER_DRIVER)
        completed += done
        revenue += done * avg_fare * m
        lost += demand - done
    return {
        "elasticity": str(elasticity),
        "cap": str(cap),
        "completed": round(completed),
        "revenue": round(revenue),
        "unserved": round(lost),
        "surge_share": round(surge_snapshots / max(1, len(snapshots)), 3),
    }


def optimise(*, days: int = 14, now: datetime | None = None) -> dict:
    from apps.rides.models import Trip, TripStatus

    now = now or timezone.now()
    since = now - timedelta(days=days)
    snapshots = list(
        SurgeSnapshot.objects.filter(computed_at__gte=since, demand__gt=0).values_list(
            "demand", "supply"
        )
    )
    avg_fare = float(
        Trip.objects.filter(status=TripStatus.COMPLETED, completed_at__gte=since).aggregate(
            a=Avg("fare_total")
        )["a"]
        or 0
    )
    if not snapshots or not avg_fare:
        return {"snapshots": len(snapshots), "policies": [], "recommended": None}
    policies = [evaluate(snapshots, e, c, avg_fare) for e, c in product(ELASTICITIES, CAPS)]
    from apps.core.conf import surge_max_multiplier

    current = evaluate(snapshots, surge.ELASTICITY, surge_max_multiplier(), avg_fare)
    # Most trips completed; revenue breaks ties (a fair price that serves more riders first).
    ranked = sorted(policies, key=lambda p: (-p["completed"], -p["revenue"]))
    best = ranked[0]
    return {
        "snapshots": len(snapshots),
        "days": days,
        "average_fare": round(avg_fare, 2),
        "current": current,
        "recommended": best,
        "uplift_completed": round(best["completed"] / max(1, current["completed"]) - 1, 4),
        "uplift_revenue": round(best["revenue"] / max(1, current["revenue"]) - 1, 4),
        "policies": ranked[:12],
        "model": {
            "rider_response": "book = 1 - min(0.6, (m - 1) x 0.5)",
            "driver_response": f"+{int(SUPPLY_RESPONSE * 100)}% supply per 1.0x of surge",
        },
    }


def propose_experiment(result: dict, *, user=None):
    """Turn the recommendation into the draft "surge-cap" A/B test (a person starts it). The
    booking code reads that experiment's ``surge_cap`` for riders in the treatment group."""
    from apps.experiments.models import Experiment, ExperimentStatus

    best = result.get("recommended")
    if not best:
        return None
    experiment = Experiment.objects.filter(key="surge-cap").first()
    if experiment and experiment.status == ExperimentStatus.RUNNING:
        return experiment  # never change a running test's treatment mid-flight
    hypothesis = (
        f"Replaying {result['snapshots']} zone snapshots, capping surge at {best['cap']}x "
        f"completes {result['uplift_completed']:+.1%} trips. Riders who see the capped price "
        "should book more often."
    )
    if experiment is None:
        experiment = Experiment(key="surge-cap", minimum_effect=0.03)
    experiment.name = f"Cap surge at {best['cap']}x"
    experiment.hypothesis = hypothesis
    experiment.treatment_config = {"surge_cap": best["cap"]}
    experiment.status = ExperimentStatus.DRAFT
    experiment.started_at = experiment.stopped_at = None
    experiment.save()
    return experiment
