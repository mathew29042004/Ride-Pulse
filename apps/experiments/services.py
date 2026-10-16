"""Feature flags and A/B tests.

* **Flags:** ``enabled(key, user)`` is True when the flag is on and the person is in the rollout
  (a stable hash of flag key and user id, so the same person always gets the same answer and
  raising 10% to 50% only adds people) or on the allow list. Unknown flags are off.
* **Assignment:** ``variant(experiment, user)`` hashes the experiment key and user id into
  0-99: stable across sessions and devices, independent between experiments, no lookups.
* **Exposure and conversion:** ``expose`` records that someone saw their variant (the moment
  the difference could change behaviour). A booking within ``CONVERSION_WINDOW`` converts their
  latest unconverted exposure; revenue is that trip's fare once completed.
* **Results** use ``stats``: conversion (z-test), revenue per exposure (Welch), the sample ratio
  check, and whether there's enough data yet for the minimum effect the test was designed for.
"""

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition

from . import stats
from .models import Experiment, ExperimentStatus, Exposure, FeatureFlag, Variant

CONVERSION_WINDOW = timedelta(minutes=15)


def bucket(salt: str, user_id: int) -> int:
    digest = hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


# --- Flags -----------------------------------------------------------------------------------


def _flag(key: str) -> FeatureFlag | None:
    cache_key = f"flag:{key}"
    flag = cache.get(cache_key)
    if flag is None:
        flag = FeatureFlag.objects.filter(key=key).first() or False
        cache.set(cache_key, flag, 30)
    return flag or None


def enabled(key: str, user=None) -> bool:
    flag = _flag(key)
    if flag is None or not flag.enabled:
        return False
    if user is not None and user.pk in flag.allow_user_ids:
        return True
    if flag.rollout_percent >= 100:
        return True
    return user is not None and bucket(f"flag:{key}", user.pk) < flag.rollout_percent


def set_flag(
    key: str, *, actor, enabled_: bool | None = None, rollout: int | None = None
) -> FeatureFlag:
    flag = FeatureFlag.objects.get(key=key)
    if rollout is not None:
        if not 0 <= rollout <= 100:
            raise BusinessRuleViolation("Rollout is 0-100%.", field="rollout_percent")
        flag.rollout_percent = rollout
    if enabled_ is not None:
        flag.enabled = enabled_
    flag.updated_by = actor
    flag.save()
    cache.delete(f"flag:{key}")
    return flag


# --- Experiments -----------------------------------------------------------------------------


def running(key: str) -> Experiment | None:
    cache_key = f"experiment:{key}"
    experiment = cache.get(cache_key)
    if experiment is None:
        experiment = (
            Experiment.objects.filter(key=key, status=ExperimentStatus.RUNNING).first() or False
        )
        cache.set(cache_key, experiment, 30)
    return experiment or None


def variant(experiment: Experiment, user) -> str:
    in_treatment = bucket(f"exp:{experiment.key}", user.pk) < experiment.treatment_percent
    return Variant.TREATMENT if in_treatment else Variant.CONTROL


def treatment_config(key: str, user) -> dict:
    """The treatment's settings for this person, or {} (control, or no experiment running)."""
    experiment = running(key)
    if experiment is None or variant(experiment, user) != Variant.TREATMENT:
        return {}
    return experiment.treatment_config


def expose(key: str, user, *, now: datetime | None = None) -> str | None:
    experiment = running(key)
    if experiment is None or user is None:
        return None
    chosen = variant(experiment, user)
    Exposure.objects.create(
        experiment=experiment, user=user, variant=chosen, at=now or timezone.now()
    )
    return chosen


def on_trip_requested(trip) -> None:
    """Credit the rider's latest unconverted exposure (per running experiment) with this trip."""
    window_start = trip.requested_at - CONVERSION_WINDOW
    for experiment in Experiment.objects.filter(status=ExperimentStatus.RUNNING):
        exposure = (
            Exposure.objects.filter(
                experiment=experiment,
                user_id=trip.rider.user_id,
                converted_at__isnull=True,
                at__gte=window_start,
                at__lte=trip.requested_at,
            )
            .order_by("-at")
            .first()
        )
        if exposure:
            Exposure.objects.filter(pk=exposure.pk).update(
                converted_at=trip.requested_at, trip=trip
            )


def start(experiment: Experiment, *, now: datetime | None = None) -> Experiment:
    if experiment.status != ExperimentStatus.DRAFT:
        raise InvalidStateTransition("Only a draft can start.")
    experiment.status, experiment.started_at = ExperimentStatus.RUNNING, now or timezone.now()
    experiment.save(update_fields=["status", "started_at"])
    cache.delete(f"experiment:{experiment.key}")
    return experiment


def stop(experiment: Experiment, *, decision: str, now: datetime | None = None) -> Experiment:
    if experiment.status != ExperimentStatus.RUNNING:
        raise InvalidStateTransition("Only a running experiment can stop.")
    experiment.status, experiment.stopped_at = ExperimentStatus.STOPPED, now or timezone.now()
    experiment.decision = decision.strip()[:200]
    experiment.save(update_fields=["status", "stopped_at", "decision"])
    cache.delete(f"experiment:{experiment.key}")
    return experiment


def results(experiment: Experiment) -> dict:
    from apps.rides.models import TripStatus

    rows = {
        r["variant"]: r
        for r in Exposure.objects.filter(experiment=experiment)
        .values("variant")
        .annotate(
            n=Count("pk"),
            users=Count("user", distinct=True),
            converted=Count("pk", filter=Q(converted_at__isnull=False)),
            completed=Count("pk", filter=Q(trip__status=TripStatus.COMPLETED)),
            revenue=Sum("trip__fare_total", filter=Q(trip__status=TripStatus.COMPLETED)),
        )
    }
    a = rows.get(
        Variant.CONTROL, {"n": 0, "users": 0, "converted": 0, "completed": 0, "revenue": None}
    )
    b = rows.get(
        Variant.TREATMENT, {"n": 0, "users": 0, "converted": 0, "completed": 0, "revenue": None}
    )
    conversion = stats.two_proportions(a["converted"], a["n"], b["converted"], b["n"])
    revenue = {}
    for name in ("control", "treatment"):
        fares = [
            float(f or 0)
            for f in Exposure.objects.filter(
                experiment=experiment, variant=getattr(Variant, name.upper())
            ).values_list("trip__fare_total", flat=True)
        ]
        n = len(fares)
        mean = sum(fares) / n if n else 0.0
        var = sum((x - mean) ** 2 for x in fares) / (n - 1) if n > 1 else 0.0
        revenue[name] = (mean, var, n)
    revenue_test = stats.welch(*revenue["control"], *revenue["treatment"])
    needed = stats.sample_size(conversion["p_a"] or 0.5, experiment.minimum_effect)
    ratio = stats.srm(a["n"], b["n"], experiment.treatment_percent / 100)
    enough = min(a["n"], b["n"]) >= needed
    significant = conversion["p_value"] is not None and conversion["p_value"] < 0.05
    if ratio["mismatch"]:
        verdict = "Assignment looks broken (sample ratio mismatch): fix it before reading results."
    elif not enough:
        verdict = f"Keep running: {min(a['n'], b['n'])} of {needed} exposures per variant needed."
    elif significant and conversion["diff"] > 0:
        verdict = "Treatment converts better, and the difference is significant."
    elif significant:
        verdict = "Treatment converts worse, and the difference is significant."
    else:
        verdict = "No clear difference in conversion at this sample size."

    def variant_row(row, mean_revenue):
        return {
            "exposures": row["n"],
            "people": row["users"],
            "conversions": row["converted"],
            "completed": row["completed"],
            "conversion_rate": row["converted"] / row["n"] if row["n"] else None,
            "revenue": str(Decimal(row["revenue"] or 0).quantize(Decimal("0.01"))),
            "revenue_per_exposure": round(mean_revenue, 2),
        }

    return {
        "key": experiment.key,
        "status": experiment.status,
        "control": variant_row(a, revenue["control"][0]),
        "treatment": variant_row(b, revenue["treatment"][0]),
        "conversion_test": conversion,
        "revenue_test": revenue_test,
        "sample_ratio": ratio,
        "needed_per_variant": needed,
        "verdict": verdict,
    }
