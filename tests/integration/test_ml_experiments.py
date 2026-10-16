"""Data science: feature flags and A/B tests (with their statistics), model serving in pure
Python, churn scoring, and the surge optimiser."""

import json
import math
import struct
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.experiments import services as experiments
from apps.experiments import stats
from apps.experiments.models import Experiment, Exposure, FeatureFlag
from apps.intelligence import ml, surge_policy
from apps.pricing.models import SurgeSnapshot
from apps.rides import services as rides
from apps.trust.models import ConsentPurpose
from apps.trust.privacy import set_consent

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# --- Statistics ------------------------------------------------------------------------------


def test_two_proportion_test_matches_the_textbook():
    # 200/1000 vs 250/1000: z ~ 2.68, p ~ 0.007 (a classic worked example).
    result = stats.two_proportions(200, 1000, 250, 1000)
    assert result["diff"] == pytest.approx(0.05)
    assert result["z"] == pytest.approx(2.68, abs=0.01)
    assert result["p_value"] == pytest.approx(0.0073, abs=0.0005)
    low, high = result["ci"]
    assert low > 0 and high < 0.1
    assert stats.two_proportions(100, 1000, 101, 1000)["p_value"] > 0.9  # no real difference


def test_sample_ratio_mismatch_and_sample_size():
    assert not stats.srm(5020, 4980, 0.5)["mismatch"]
    assert stats.srm(5600, 4400, 0.5)["mismatch"]  # 56/44 on a 50/50 test: broken assignment
    # 20% baseline, detect +3 points with 80% power: ~2,900 per variant.
    assert 2700 < stats.sample_size(0.20, 0.03) < 3100


# --- Flags and assignment --------------------------------------------------------------------


def test_flags_roll_out_by_stable_hash(ops):
    riders = [make_rider() for _ in range(40)]
    FeatureFlag.objects.create(key="new-thing", description="x", enabled=True, rollout_percent=25)
    on = {r.pk for r in riders if experiments.enabled("new-thing", r.user)}
    assert 0 < len(on) < 40
    assert on == {r.pk for r in riders if experiments.enabled("new-thing", r.user)}  # stable
    experiments.set_flag("new-thing", actor=ops, rollout=75)
    wider = {r.pk for r in riders if experiments.enabled("new-thing", r.user)}
    assert on <= wider  # raising the rollout only adds people
    experiments.set_flag("new-thing", actor=ops, enabled_=False)
    assert not any(experiments.enabled("new-thing", r.user) for r in riders)  # kill switch
    assert not experiments.enabled("no-such-flag", riders[0].user)


def test_share_rides_flag_hides_the_ride_type(mini, make_driver, now, ops):
    rider = make_rider()
    make_driver(now=now)

    def codes():
        options = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now)
        return {o["ride_type"].code for o in options["options"]}

    assert "SHARE" in codes()
    experiments.set_flag("share-rides", actor=ops, enabled_=False)
    assert "SHARE" not in codes()


def test_surge_cap_experiment_end_to_end(mini, make_driver, now, chennai):
    from apps.geo.models import Zone

    zone = Zone.objects.get(city=chennai, name="T. Nagar")
    SurgeSnapshot.objects.create(
        zone=zone, multiplier=Decimal("2.8"), demand=30, supply=5, computed_at=now
    )
    experiment = Experiment.objects.create(
        key="surge-cap", name="Cap surge", hypothesis="h", treatment_config={"surge_cap": "1.5"}
    )
    experiments.start(experiment, now=now)
    make_driver(now=now)
    riders = [make_rider() for _ in range(12)]
    seen = {}
    for rider in riders:
        options = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now)[
            "options"
        ]
        seen[rider.pk] = next(o for o in options if o["ride_type"].code == "MINI")[
            "estimate"
        ].surge_multiplier
    groups = {r.pk: experiments.variant(experiment, r.user) for r in riders}
    assert {seen[pk] for pk, v in groups.items() if v == "treatment"} <= {Decimal("1.5")}
    assert {seen[pk] for pk, v in groups.items() if v == "control"} <= {Decimal("2.8")}
    assert Exposure.objects.filter(experiment=experiment).count() == 12

    # Booking right after seeing the price converts the exposure (and is charged the same cap).
    treated = next(r for r in riders if groups[r.pk] == "treatment")
    trip = book(treated, mini, now=now + timedelta(minutes=1))
    assert trip.surge_multiplier == Decimal("1.5")
    assert Exposure.objects.get(user=treated.user).trip == trip
    result = experiments.results(experiment)
    assert result["treatment"]["conversions"] == 1
    assert "Keep running" in result["verdict"]  # far too little data to decide


# --- Models in pure Python -------------------------------------------------------------------


def write_model(tmp_path, name, body):
    (tmp_path / f"{name}.json").write_text(json.dumps(body))


def test_eta_trees_score_in_pure_python(tmp_path, settings, chennai, mini):
    settings.ML_MODELS_DIR = tmp_path
    assert (
        ml.predict_minutes(
            estimate_min=20,
            distance_km=8,
            at=timezone.now(),
            rain_mm=0,
            airport=False,
            central=False,
            city="chennai",
            ride_type="MINI",
        )
        is None
    )
    # One stump: rain_mm (feature 4) above 2 mm adds log(1.3) to the ratio.
    stump = {
        "left": [1, -1, -1],
        "right": [2, -1, -1],
        "feature": [4, -2, -2],
        "threshold": [2.0, -2, -2],
        "value": [0, 0.0, math.log(1.3)],
    }
    write_model(
        tmp_path,
        "eta",
        {
            "kind": "gradient_boosted_trees",
            "target": "log ratio",
            "features": {
                "numeric": [
                    "estimated_duration_min",
                    "estimated_distance_km",
                    "hour",
                    "weekday",
                    "rain_mm",
                ],
                "flags": ["weekend", "airport", "central"],
                "cities": ["chennai"],
                "ride_types": ["MINI"],
            },
            "init": 0.0,
            "learning_rate": 1.0,
            "trees": [stump],
            "metrics": {},
        },
    )
    dry = ml.predict_minutes(
        estimate_min=20,
        distance_km=8,
        at=timezone.now(),
        rain_mm=0,
        airport=False,
        central=False,
        city="chennai",
        ride_type="MINI",
    )
    wet = ml.predict_minutes(
        estimate_min=20,
        distance_km=8,
        at=timezone.now(),
        rain_mm=5,
        airport=False,
        central=False,
        city="chennai",
        ride_type="MINI",
    )
    assert dry == pytest.approx(20) and wet == pytest.approx(26)
    options = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=timezone.now())[
        "options"
    ]
    assert all(o["predicted_duration_min"] for o in options)  # the estimate now carries it


def test_churn_scores_and_win_back_respects_consent(tmp_path, settings, mini, make_driver, now):
    settings.ML_MODELS_DIR = tmp_path
    features = [
        "trips_28d",
        "trips_56d",
        "failed_56d",
        "days_since_last",
        "avg_fare",
        "surge_share",
        "promo_share",
        "tickets_56d",
    ]
    write_model(
        tmp_path,
        "churn",
        {
            "kind": "logistic_regression",
            "target": "no trip in 28 days",
            "features": features,
            "mean": [0] * 8,
            "scale": [1] * 8,
            "coefficients": [0, 0, 0, 0.2, 0, 0, 0, 0],  # only recency matters
            "intercept": -1.0,
            "metrics": {},
        },
    )
    quiet, busy = make_rider(), make_rider()
    make_driver(now=now)
    old = drive_to_completion(book(quiet, mini, now=now), now=now)
    from apps.rides.models import Trip

    Trip.objects.filter(pk=old.pk).update(
        requested_at=now - timedelta(days=30), completed_at=now - timedelta(days=30)
    )
    later = now + timedelta(hours=1)
    make_driver(now=later)  # a driver online right where the next ride starts
    drive_to_completion(book(busy, mini, now=later), now=later)
    ranked = ml.at_risk(now=now + timedelta(hours=3))
    assert ranked[0]["rider_id"] == quiet.pk and ranked[0]["probability"] > ranked[1]["probability"]
    assert ml.win_back([quiet.pk], title="We miss you", body="20% off") == 0  # no consent
    set_consent(quiet.user, ConsentPurpose.MARKETING, True)
    assert ml.win_back([quiet.pk], title="We miss you", body="20% off") == 1


# --- Surge optimiser -------------------------------------------------------------------------


def test_surge_optimiser_ranks_policies_and_proposes_a_test(chennai, mini, make_driver, now):
    from apps.geo.models import Zone

    zone = Zone.objects.filter(city=chennai).first()
    for demand, supply in [(40, 5), (25, 10), (8, 8), (60, 6), (12, 3)]:
        SurgeSnapshot.objects.create(
            zone=zone, multiplier=Decimal(1), demand=demand, supply=supply, computed_at=now
        )
    make_driver(now=now)
    drive_to_completion(book(make_rider(), mini, now=now), now=now)
    result = surge_policy.optimise(now=now + timedelta(hours=1))
    assert result["snapshots"] == 5 and result["policies"]
    best = result["recommended"]
    assert best["completed"] >= result["current"]["completed"]
    experiment = surge_policy.propose_experiment(result)
    assert experiment.key == "surge-cap" and experiment.status == "DRAFT"
    assert experiment.treatment_config == {"surge_cap": best["cap"]}


def test_tree_churn_model_and_float32_thresholds(tmp_path, settings):
    settings.ML_MODELS_DIR = tmp_path
    # One split on overdue_ratio at a threshold that only float32 rounding gets right:
    # float32(4.57142857) is just above it, so the rider goes right (high risk).
    as_f32 = struct.unpack("f", struct.pack("f", 4.57142857))[0]
    threshold = as_f32 - 1e-7  # between the float32 value and the plain float64 4.57142857
    stump = {
        "left": [1, -1, -1],
        "right": [2, -1, -1],
        "feature": [1, -2, -2],
        "threshold": [threshold, -2, -2],
        "value": [0, -2.0, 2.0],
    }
    model = {
        "kind": "gradient_boosted_trees",
        "features": ["days_since_last", "overdue_ratio"],
        "init": 0.0,
        "learning_rate": 1.0,
        "trees": [stump],
    }
    risky = ml.churn_probability(model, {"days_since_last": 32, "overdue_ratio": 4.57142857})
    calm = ml.churn_probability(model, {"days_since_last": 3, "overdue_ratio": 0.5})
    assert risky == pytest.approx(1 / (1 + math.exp(-2))) and calm < 0.2
