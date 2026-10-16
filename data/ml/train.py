"""Train Ride Pulse's models from the warehouse and export them as JSON for the app.

* **ETA** (gradient-boosted trees): predicts how long a ride really takes. Its target is the
  log of (actual minutes / the app's estimate), so the model learns corrections to the estimate:
  city, time of week, rain, the centre, airports, vehicle. Evaluated on the most recent 20% of
  rides (a time split, never shuffled: the model must predict the future) against the app's
  estimate alone.
* **Rider churn** (logistic regression): the chance an active rider takes no trip in the next
  28 days. Evaluated by ROC AUC on the newest weekly snapshot, trained on the older ones.

Both are exported as plain JSON (trees and coefficients) so the app scores them in pure Python
without scikit-learn. ``models/*.json`` also records the training date, data size and metrics.

    cd data && .venv/bin/python -m ml.train
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
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
        "threshold": [round(x, 6) for x in t.threshold.tolist()],
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
    mean, scale = x_train.mean(axis=0), x_train.std(axis=0)
    scale[scale == 0] = 1.0
    model = LogisticRegression(max_iter=1000)
    model.fit((x_train - mean) / scale, y_train)
    scores = model.predict_proba((x_test - mean) / scale)[:, 1]
    auc = float(roc_auc_score(y_test, scores)) if len(set(y_test)) > 1 else None
    # How much better than "recency only" (days since the last trip), the obvious heuristic?
    recency = x_test[:, CHURN_FEATURES.index("days_since_last")]
    recency_auc = float(roc_auc_score(y_test, recency)) if len(set(y_test)) > 1 else None
    return {
        "kind": "logistic_regression",
        "target": "no completed trip in the next 28 days",
        "features": CHURN_FEATURES,
        "mean": mean.round(6).tolist(),
        "scale": scale.round(6).tolist(),
        "coefficients": model.coef_[0].round(6).tolist(),
        "intercept": round(float(model.intercept_[0]), 6),
        "metrics": {
            "train_rows": len(train),
            "test_rows": len(test),
            "test_cutoff": str(newest),
            "churn_rate": round(float(y_test.mean()), 3),
            "auc": round(auc, 3) if auc is not None else None,
            "recency_only_auc": round(recency_auc, 3) if recency_auc is not None else None,
        },
    }


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
