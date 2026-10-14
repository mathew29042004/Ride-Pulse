"""Extract: copy the app's PostgreSQL data into the data lake as Parquet files.

* Reference and current-state tables (cities, drivers, trips, …) are written as dated
  **snapshots**: ``lake/raw/<table>/snapshot=<UTC timestamp>/data.parquet`` (last 7 kept).
* Append-only history (trip events, ledger entries) is extracted **incrementally**: only rows
  with an id above the last run's watermark, as ``lake/raw/<table>/batch=<timestamp>/``.

Privacy by design: names, phone numbers, emails, number plates, addresses, ride PINs and share
tokens never leave the app. Coordinates are rounded to ~100 m. Riders and drivers appear only as
internal ids.

Run with the data virtualenv:  data/.venv/bin/python -m pipeline.extract  (from data/)
"""

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import duckdb

DATA_DIR = Path(__file__).resolve().parent.parent
LAKE = DATA_DIR / "lake" / "raw"
STATE_FILE = DATA_DIR / "lake" / "_state.json"
KEEP_SNAPSHOTS = 7
DEFAULT_DB = "postgres://ridepulse:ridepulse@127.0.0.1:5433/ridepulse"


@dataclass(frozen=True)
class Table:
    name: str
    sql: str  # SELECT over the attached database "pg"
    incremental_on: str | None = None  # id column for append-only tables


TABLES = [
    Table(
        "cities",
        "SELECT id, name, slug, state, center_lat, center_lng, radius_km, fare_multiplier, "
        "is_active FROM pg.public.geo_city",
    ),
    Table(
        "zones",
        "SELECT id, city_id, code, name, center_lat, center_lng, radius_km, is_airport, "
        "demand_weight FROM pg.public.geo_zone",
    ),
    Table(
        "ride_types",
        "SELECT id, code, name, seats, service, vehicle_type_id, service_start_hour, "
        "service_end_hour, is_active FROM pg.public.pricing_ridetype",
    ),
    Table(
        "drivers",
        "SELECT d.id, d.city_id, d.created_at, d.approved_at, d.onboarding_status, d.gender, "
        "d.rating, d.rating_count, d.acceptance_rate, d.completed_trips, d.cancelled_trips, "
        "d.safety_score, d.accepts_parcels, d.accepts_intercity, d.fleet_executive_id "
        "FROM pg.public.drivers_driverprofile d",
    ),
    Table(
        "vehicles",
        "SELECT id, driver_id, ride_type_id, make, model, year, seats, fuel_type, is_active "
        "FROM pg.public.drivers_vehicle",
    ),
    Table(
        "riders",
        "SELECT r.id, r.created_at, r.rating, r.rating_count, r.completed_trips, "
        "r.default_payment_method, r.is_blocked, r.night_safety, r.eco_points, r.co2_saved_g, "
        "r.referred_by_id IS NOT NULL AS was_referred, u.language, "
        "u.email LIKE '%@example.com' AS is_simulated "
        "FROM pg.public.riders_riderprofile r JOIN pg.public.accounts_user u ON u.id = r.user_id",
    ),
    Table(
        "staff",
        "SELECT s.id, s.employee_id, u.role, s.title, s.department, s.state, s.city_id, "
        "s.reports_to_id, s.joined_on FROM pg.public.accounts_staffprofile s "
        "JOIN pg.public.accounts_user u ON u.id = s.user_id",
    ),
    Table(
        "trips",
        "SELECT id, trip_number, service, status, city_id, rider_id, driver_id, vehicle_id, "
        "ride_type_id, pickup_zone_id, dropoff_zone_id, "
        "round(pickup_lat, 3) AS pickup_lat, round(pickup_lng, 3) AS pickup_lng, "
        "round(dropoff_lat, 3) AS dropoff_lat, round(dropoff_lng, 3) AS dropoff_lng, "
        "payment_method, payment_status, pricing_mode, surge_multiplier, "
        "estimated_distance_km, estimated_duration_min, estimated_fare, actual_distance_km, "
        "actual_duration_min, waiting_minutes, fare_total, driver_earning, platform_commission, "
        "gst_amount, discount_amount, tip_amount, cancellation_fee, boost_amount, tip_pledged, "
        "fare_offer, offer_adjustment, sure_ride_minutes, sure_ride_refunded_at IS NOT NULL "
        "AS sure_ride_refunded, ride_pass_applied, fare_lock_id IS NOT NULL AS fare_locked, "
        "promo_id IS NOT NULL AS used_promo, night_safe, co2_saved_g, package_hours, "
        "round_trip, trip_days, cancelled_by, flags, preferences, dispatch_attempts, "
        "dispatch_round, harsh_brakes, harsh_accelerations, speeding_seconds, "
        "requested_at, assigned_at, arrived_at, started_at, completed_at, cancelled_at, "
        "pickup_eta_min FROM pg.public.rides_trip",
    ),
    Table(
        "trip_offers",
        "SELECT id, trip_id, driver_id, status, offered_at, responded_at, distance_km, "
        "eta_minutes, rank_score, dispatch_mode, round, counter_amount "
        "FROM pg.public.rides_tripoffer",
    ),
    Table(
        "ratings",
        "SELECT id, trip_id, direction, stars, tags, created_at FROM pg.public.rides_triprating",
    ),
    Table(
        "parcels",
        "SELECT id, trip_id, category, weight_kg, code_attempts, delivered_at "
        "FROM pg.public.rides_parceldelivery",
    ),
    Table(
        "payments",
        "SELECT id, created_at, purpose, method, amount, status, trip_id "
        "FROM pg.public.payments_payment",
    ),
    Table(
        "support_tickets",
        "SELECT id, created_at, category, priority, status, sla_due_at, escalated, resolved_at, "
        "refund_amount, trip_id FROM pg.public.support_supportticket",
    ),
    Table(
        "driver_sessions",
        "SELECT id, driver_id, started_at, ended_at FROM pg.public.drivers_driversession",
    ),
    Table(
        "ride_checks",
        "SELECT id, trip_id, kind, status, driver_ok, created_at, answered_at "
        "FROM pg.public.rides_ridecheck",
    ),
    Table(
        "trip_events",
        "SELECT id, trip_id, kind, from_status, to_status, created_at "
        "FROM pg.public.rides_tripevent",
        incremental_on="id",
    ),
    Table(
        "ledger_entries",
        "SELECT e.id, e.transaction_id, t.kind, t.created_at, t.trip_id, "
        "CASE WHEN e.wallet_id IS NULL THEN e.account ELSE 'wallet' END AS account, e.amount "
        "FROM pg.public.payments_ledgerentry e "
        "JOIN pg.public.payments_ledgertransaction t ON t.id = e.transaction_id",
        incremental_on="e.id",
    ),
]


def _libpq(url: str) -> str:
    parts = urlparse(url)
    return (
        f"host={parts.hostname} port={parts.port or 5432} dbname={parts.path.lstrip('/')} "
        f"user={parts.username} password={parts.password or ''}"
    )


def _database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    env_file = DATA_DIR.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return DEFAULT_DB


def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"watermarks": {}}


def _prune(folder: Path) -> None:
    snapshots = sorted(p for p in folder.glob("snapshot=*") if p.is_dir())
    for old in snapshots[:-KEEP_SNAPSHOTS]:
        shutil.rmtree(old)


def extract(log=print) -> dict:
    """Run one extraction. Returns rows written per table."""
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    state = _load_state()
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{_libpq(_database_url())}' AS pg (TYPE postgres, READ_ONLY)")
    written: dict[str, int] = {}
    for table in TABLES:
        folder = LAKE / table.name
        if table.incremental_on:
            column = table.incremental_on
            after = state["watermarks"].get(table.name, 0)
            sql = f"{table.sql} WHERE {column} > {int(after)}"
            target = folder / f"batch={run}"
        else:
            sql = table.sql
            target = folder / f"snapshot={run}"
        rows = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        if rows == 0:
            written[table.name] = 0
            continue
        target.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY ({sql}) TO '{target / 'data.parquet'}' (FORMAT parquet, COMPRESSION zstd)"
        )
        if table.incremental_on:
            plain = table.incremental_on.split(".")[-1]
            state["watermarks"][table.name] = con.execute(
                f"SELECT max({plain}) FROM read_parquet('{target / 'data.parquet'}')"
            ).fetchone()[0]
        else:
            _prune(folder)
        written[table.name] = rows
        log(f"  {table.name}: {rows:,} rows")
    state["last_run"] = run
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return written


if __name__ == "__main__":
    totals = extract()
    print(f"Extracted {sum(totals.values()):,} rows from {len(totals)} tables.")
