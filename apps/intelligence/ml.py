"""Serving the trained models inside the app, in plain Python.

The data platform trains the models (``data/ml/train.py``) and exports them as JSON: trees for
ETA, coefficients for churn. This module scores them with no scikit-learn in the app, reloading
a model when its file changes. Without a model file, callers fall back to the app's own rules.
"""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

_cache: dict[str, tuple[float, dict]] = {}


def _path(name: str) -> Path:
    return (
        Path(getattr(settings, "ML_MODELS_DIR", Path(settings.BASE_DIR) / "data" / "models"))
        / f"{name}.json"
    )


def load(name: str) -> dict | None:
    path = _path(name)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    model = json.loads(path.read_text())
    if "skipped" in model:
        return None
    _cache[name] = (mtime, model)
    return model


# --- ETA -------------------------------------------------------------------------------------


def _walk(tree: dict, x: list[float]) -> float:
    node = 0
    while tree["left"][node] != -1:
        node = (
            tree["left"][node]
            if x[tree["feature"][node]] <= tree["threshold"][node]
            else tree["right"][node]
        )
    return tree["value"][node]


def eta_vector(
    model: dict,
    *,
    estimate_min: float,
    distance_km: float,
    at: datetime,
    rain_mm: float,
    airport: bool,
    central: bool,
    city: str,
    ride_type: str,
) -> list[float]:
    local = timezone.localtime(at)
    numeric = {
        "estimated_duration_min": estimate_min,
        "estimated_distance_km": distance_km,
        "hour": local.hour,
        "weekday": local.isoweekday(),
        "rain_mm": rain_mm,
    }
    flags = {"weekend": local.isoweekday() >= 6, "airport": airport, "central": central}
    spec = model["features"]
    return (
        [float(numeric[name]) for name in spec["numeric"]]
        + [1.0 if flags[name] else 0.0 for name in spec["flags"]]
        + [1.0 if city == c else 0.0 for c in spec["cities"]]
        + [1.0 if ride_type == t else 0.0 for t in spec["ride_types"]]
    )


def predict_minutes(*, estimate_min: float, **features) -> float | None:
    """The model's ride time, or None when no ETA model is trained yet."""
    model = load("eta")
    if model is None:
        return None
    x = eta_vector(model, estimate_min=estimate_min, **features)
    log_ratio = model["init"] + model["learning_rate"] * sum(
        _walk(tree, x) for tree in model["trees"]
    )
    return estimate_min * math.exp(log_ratio)


def predict_for(
    city, ride_type, pickup, dropoff, *, estimate_min: float, distance_km: float, at, zones=()
) -> float | None:
    from apps.geo.distance import haversine_km

    from .context import current_weather

    reading = current_weather(city.pk, now=at)
    central = (
        min(
            haversine_km(pickup[0], pickup[1], city.center_lat, city.center_lng),
            haversine_km(dropoff[0], dropoff[1], city.center_lat, city.center_lng),
        )
        < 3
    )
    airport = any(z is not None and z.is_airport for z in zones)
    return predict_minutes(
        estimate_min=estimate_min,
        distance_km=distance_km,
        at=at,
        rain_mm=float(reading.rain_mm) if reading else 0.0,
        airport=airport,
        central=central,
        city=city.slug,
        ride_type=ride_type.code,
    )


# --- Churn -----------------------------------------------------------------------------------


def churn_features(*, now: datetime | None = None) -> dict[int, dict]:
    """The churn features for every rider active in the last 56 days, computed live."""
    from apps.rides.models import Trip, TripStatus
    from apps.support.models import SupportTicket

    now = now or timezone.now()
    since = now - timedelta(days=56)
    month = now - timedelta(days=28)
    rides = Trip.objects.filter(service="RIDE", requested_at__gte=since, requested_at__lt=now)
    rows = rides.values("rider_id").annotate(
        trips_28d=Count("pk", filter=Q(status=TripStatus.COMPLETED, requested_at__gte=month)),
        trips_56d=Count("pk", filter=Q(status=TripStatus.COMPLETED)),
        failed_56d=Count(
            "pk", filter=Q(status__in=[TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND])
        ),
        last=Max("requested_at", filter=Q(status=TripStatus.COMPLETED)),
        avg_fare=Avg("fare_total", filter=Q(status=TripStatus.COMPLETED)),
        surge=Count("pk", filter=Q(surge_multiplier__gt=1)),
        promo=Count("pk", filter=Q(promo__isnull=False)),
        n=Count("pk"),
    )
    tickets = dict(
        SupportTicket.objects.filter(created_at__gte=since, trip__isnull=False)
        .values_list("trip__rider_id")
        .annotate(k=Count("pk"))
        .values_list("trip__rider_id", "k")
    )
    out = {}
    for r in rows:
        if not r["trips_56d"]:
            continue
        out[r["rider_id"]] = {
            "trips_28d": r["trips_28d"],
            "trips_56d": r["trips_56d"],
            "failed_56d": r["failed_56d"],
            "days_since_last": (now - r["last"]).days if r["last"] else 56,
            "avg_fare": float(r["avg_fare"] or 0),
            "surge_share": r["surge"] / r["n"],
            "promo_share": r["promo"] / r["n"],
            "tickets_56d": tickets.get(r["rider_id"], 0),
        }
    return out


def churn_probability(model: dict, features: dict) -> float:
    z = model["intercept"] + sum(
        coef * (float(features[name]) - mean) / scale
        for name, coef, mean, scale in zip(
            model["features"], model["coefficients"], model["mean"], model["scale"], strict=True
        )
    )
    return 1 / (1 + math.exp(-z))


def at_risk(*, limit: int = 50, now: datetime | None = None) -> list[dict]:
    from apps.riders.models import RiderProfile
    from apps.trust.models import ConsentPurpose

    model = load("churn")
    if model is None:
        return []
    scored = sorted(
        (
            (churn_probability(model, f), rider_id, f)
            for rider_id, f in churn_features(now=now).items()
        ),
        reverse=True,
    )[:limit]
    riders = RiderProfile.objects.select_related("user").in_bulk([rid for _, rid, _ in scored])
    from apps.trust.privacy import consenting

    opted_in = consenting([r.user_id for r in riders.values()], ConsentPurpose.MARKETING)
    rows = []
    for p, rider_id, f in scored:
        rider = riders.get(rider_id)
        if rider is None:
            continue
        rows.append(
            {
                "rider_id": rider_id,
                "name": rider.user.get_full_name(),
                "probability": round(p, 3),
                "days_since_last": f["days_since_last"],
                "trips_56d": f["trips_56d"],
                "failed_56d": f["failed_56d"],
                "can_message": rider.user_id in opted_in,
            }
        )
    return rows


def win_back(rider_ids: list[int], *, title: str, body: str) -> int:
    """A win-back offer, only to at-risk riders who opted in to offers."""
    from apps.notifications.models import Level
    from apps.notifications.services import notify
    from apps.riders.models import RiderProfile
    from apps.trust.models import ConsentPurpose
    from apps.trust.privacy import has_consent

    sent = 0
    for rider in RiderProfile.objects.filter(pk__in=rider_ids).select_related("user"):
        if has_consent(rider.user, ConsentPurpose.MARKETING):
            notify(rider.user, title[:160], body[:300], level=Level.INFO, link="/ride")
            sent += 1
    return sent


def model_cards() -> dict:
    cards = {}
    for name in ("eta", "churn"):
        model = load(name)
        cards[name] = (
            {
                "trained_at": model.get("trained_at"),
                "kind": model["kind"],
                "target": model["target"],
                "metrics": model["metrics"],
            }
            if model
            else None
        )
    return cards
