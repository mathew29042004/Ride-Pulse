"""Train Ride Pulse's models from the warehouse and export them as JSON for the app.

* **ETA** (gradient-boosted trees): predicts how long a ride really takes. Its target is the
  log of (actual minutes / the app's estimate), so the model learns corrections to the estimate:
  city, time of week, rain, the centre, airports, vehicle. Evaluated on the most recent 20% of
  rides (a time split, never shuffled: the model must predict the future) against the app's
  estimate alone.
* **Rider churn** (gradient-boosted trees): the chance an active rider takes no trip in the next
  28 days. Features include the rider's own rhythm (usual gap between rides, how overdue they
  are now, rising or fading). Evaluated by ROC AUC on the newest weekly snapshot, trained on the
  older ones, against "days since last ride" alone, with a bootstrap of the test set to show how
  often the model really wins (few riders churn, so one AUC number can mislead).

Both are exported as plain JSON (trees and coefficients) so the app scores them in pure Python
without scikit-learn. ``models/*.json`` also records the training date, data size and metrics.

    cd data && .venv/bin/python -m ml.train
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import roc_auc_score

DATA_DIR = Path(__file__).resolve().parent.parent
WAREHOUSE = DATA_DIR / "warehouse" / "ridepulse.duckdb"
MODELS = DATA_DIR / "models"

ETA_NUMERIC = ["estimated_duration_min", "estimated_distance_km", "hour", "weekday", "rain_mm"]
ETA_FLAGS = ["weekend", "airport", "central"]
CHURN_FEATURES = [
    "trips_28d",
    "trips_56d",
    "failed_56d",
    "days_since_last",
    "avg_fare",
    "surge_share",
    "promo_share",
    "tickets_56d",
    "avg_gap_days",
    "overdue_ratio",
    "trend",
]


def _rows(sql: str) -> list[dict]:
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        cursor = con.execute(sql)
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


# --- ETA -------------------------------------------------------------------------------------


def eta_features(rows: list[dict], cities: list[str], types: list[str]) -> np.ndarray:
    matrix = []
    for r in rows:
        values = [float(r[c] or 0) for c in ETA_NUMERIC] + [1.0 if r[c] else 0.0 for c in ETA_FLAGS]
        values += [1.0 if r["city"] == c else 0.0 for c in cities]
        values += [1.0 if r["ride_type"] == t else 0.0 for t in types]
        matrix.append(values)
    return np.array(matrix)


def _tree_json(tree) -> dict:
    t = tree.tree_
    return {
        "left": t.children_left.tolist(),
        "right": t.children_right.tolist(),
        "feature": t.feature.tolist(),
        # Full precision: scikit-learn compares float32 features against these exactly.
        "threshold": t.threshold.tolist(),
        "value": [round(v[0][0], 6) for v in t.value.tolist()],
    }


def train_eta() -> dict:
    rows = _rows("select * from ml.ml_eta_training order by ride_date, trip_id")
    if len(rows) < 500:
        return {"skipped": f"only {len(rows)} rides"}
    cities = sorted({r["city"] for r in rows})
    types = sorted({r["ride_type"] for r in rows})
    x = eta_features(rows, cities, types)
    actual = np.array([float(r["ride_minutes"]) for r in rows])
    estimate = np.array([float(r["estimated_duration_min"]) for r in rows])
    y = np.log(actual / estimate)
    split = int(len(rows) * 0.8)  # time order: train on the past, test on the newest 20%
    model = GradientBoostingRegressor(
        n_estimators=150, max_depth=3, learning_rate=0.08, subsample=0.8, random_state=7
    )
    model.fit(x[:split], y[:split])
    predicted = estimate[split:] * np.exp(model.predict(x[split:]))

    def mae(pred):
        return float(np.mean(np.abs(pred - actual[split:])))

    def mape(pred):
        return float(np.mean(np.abs(pred - actual[split:]) / actual[split:]))

    names = (
        ETA_NUMERIC + ETA_FLAGS + [f"city={c}" for c in cities] + [f"ride_type={t}" for t in types]
    )
    importance = sorted(
        zip(names, model.feature_importances_.tolist(), strict=True), key=lambda kv: -kv[1]
    )
    metrics = {
        "train_rows": split,
        "test_rows": len(rows) - split,
        "baseline_mae_min": round(mae(estimate[split:]), 2),
        "model_mae_min": round(mae(predicted), 2),
        "baseline_mape": round(mape(estimate[split:]), 4),
        "model_mape": round(mape(predicted), 4),
        "top_features": [[name, round(score, 3)] for name, score in importance[:8]],
    }
    metrics["improvement"] = round(1 - metrics["model_mae_min"] / metrics["baseline_mae_min"], 3)
    return {
        "kind": "gradient_boosted_trees",
        "target": "log(actual_minutes / estimated_minutes)",
        "features": {
            "numeric": ETA_NUMERIC,
            "flags": ETA_FLAGS,
            "cities": cities,
            "ride_types": types,
        },
        "init": float(model.init_.constant_.ravel()[0]),
        "learning_rate": model.learning_rate,
        "trees": [_tree_json(est[0]) for est in model.estimators_],
        "metrics": metrics,
    }


# --- Churn -----------------------------------------------------------------------------------


def train_churn() -> dict:
    rows = _rows("select * from ml.ml_rider_churn order by cutoff, rider_id")
    if len(rows) < 200:
        return {"skipped": f"only {len(rows)} rider snapshots"}
    newest = max(r["cutoff"] for r in rows)
    train = [r for r in rows if r["cutoff"] < newest]
    test = [r for r in rows if r["cutoff"] == newest]
    if not train or not test:
        return {"skipped": "need at least two weekly snapshots"}

    def matrix(part):
        return np.array([[float(r[c] or 0) for c in CHURN_FEATURES] for r in part])

    x_train, x_test = matrix(train), matrix(test)
    y_train = np.array([1 if r["churned"] else 0 for r in train])
    y_test = np.array([1 if r["churned"] else 0 for r in test])
    model = GradientBoostingClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=7
    )
    model.fit(x_train, y_train)
    prior = float(np.clip(y_train.mean(), 1e-6, 1 - 1e-6))
    init = float(np.log(prior / (1 - prior)))
    trees = [_tree_json(est[0]) for est in model.estimators_]
    scores = model.predict_proba(x_test)[:, 1]
    # The exported trees must score exactly like scikit-learn (the app walks them itself).
    raw = init + model.learning_rate * sum(np.array([_walk(t, x) for x in x_test]) for t in trees)
    assert np.allclose(1 / (1 + np.exp(-raw)), scores, atol=1e-4), "exported trees disagree"
    recency = x_test[:, CHURN_FEATURES.index("days_since_last")]
    two_classes = len(set(y_test)) > 1
    auc = float(roc_auc_score(y_test, scores)) if two_classes else None
    recency_auc = float(roc_auc_score(y_test, recency)) if two_classes else None
    wins = None
    if two_classes:
        rng = np.random.default_rng(7)
        better = total = 0
        for _ in range(1000):
            pick = rng.integers(0, len(y_test), len(y_test))
            if len(set(y_test[pick])) < 2:
                continue
            total += 1
            better += roc_auc_score(y_test[pick], scores[pick]) > roc_auc_score(
                y_test[pick], recency[pick]
            )
        wins = round(better / total, 3) if total else None
    importance = sorted(
        zip(CHURN_FEATURES, model.feature_importances_.tolist(), strict=True), key=lambda kv: -kv[1]
    )
    return {
        "kind": "gradient_boosted_trees",
        "target": "no completed trip in the next 28 days",
        "features": CHURN_FEATURES,
        "init": init,
        "learning_rate": model.learning_rate,
        "trees": trees,
        "metrics": {
            "train_rows": len(train),
            "test_rows": len(test),
            "test_cutoff": str(newest),
            "churned_in_test": int(y_test.sum()),
            "churn_rate": round(float(y_test.mean()), 3),
            "auc": round(auc, 3) if auc is not None else None,
            "recency_only_auc": round(recency_auc, 3) if recency_auc is not None else None,
            "beats_recency_share": wins,
            "top_features": [[n, round(v, 3)] for n, v in importance[:5]],
        },
    }


def _walk(tree: dict, x) -> float:
    """Score one tree the way the app does (features as float32, like scikit-learn)."""
    x = np.asarray(x, dtype=np.float32)
    node = 0
    while tree["left"][node] != -1:
        node = (
            tree["left"][node]
            if x[tree["feature"][node]] <= tree["threshold"][node]
            else tree["right"][node]
        )
    return tree["value"][node]


def main() -> None:
    MODELS.mkdir(exist_ok=True)
    trained_at = datetime.now(UTC).isoformat(timespec="seconds")
    for name, trainer in (("eta", train_eta), ("churn", train_churn)):
        model = trainer()
        model["trained_at"] = trained_at
        (MODELS / f"{name}.json").write_text(json.dumps(model))
        print(f"{name}: {json.dumps(model.get('metrics') or model.get('skipped'))}")


if __name__ == "__main__":
    main()
