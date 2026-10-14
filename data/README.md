# Ride Pulse data platform

A batch analytics platform next to the app. It doesn't change the app: it copies the app's data
out, models it, tests it, and reports on it.

```
PostgreSQL (app)
   │  pipeline/extract.py   privacy-filtered copy, snapshots + incremental batches
   ▼
lake/raw/<table>/…/data.parquet          (Parquet, zstd)
   │  dbt (dbt-duckdb)
   ▼
warehouse/ridepulse.duckdb
   ├─ staging.*    one cleaned view per lake table (newest snapshot, IST time columns)
   ├─ core.*       star schema: fct_trips, fct_dispatch_offers, fct_driver_sessions,
   │               dim_city, dim_zone, dim_driver, dim_rider, dim_ride_type, dim_date
   └─ reporting.*  rpt_city_daily, rpt_hourly_demand, rpt_driver_weekly, rpt_service_mix,
                   rpt_cancellations, rpt_dispatch_funnel, rpt_support_sla, rpt_org_coverage
   │  pipeline/report.py
   ▼
reports/insights.md

Orchestrated by Dagster (orchestration/definitions.py): one asset per lake table → dbt models
and tests → insights report, refreshed daily at 02:00 IST.
```

## Quick start

From the project root (the app's database must be running):

```bash
make data-setup     # once: data/.venv with DuckDB, dbt and Dagster (~550 MB)
make history        # optional: 60 days of trips in all 33 cities (stop the simulator first)
make data-run       # extract → dbt build (models + tests) → reports/insights.md
make data-ui        # Dagster at http://localhost:3000
```

Explore the warehouse yourself:

```bash
cd data && .venv/bin/duckdb warehouse/ridepulse.duckdb   # or: .venv/bin/python -c "import duckdb…"
select city, sum(gross_bookings) from reporting.rpt_city_daily group by city order by 2 desc;
```

## Design choices

* **Separate virtualenv.** dbt and Dagster pull in many dependencies; keeping them in
  `data/.venv` means they can never break the app.
* **Privacy by design.** Names, phone numbers, emails, number plates, addresses, ride PINs and
  share tokens never leave the app. Pickup/drop coordinates are rounded to ~100 m. Riders and
  drivers are internal ids only. (In line with India's DPDP Act: collect for a purpose, minimise.)
* **Snapshots vs increments.** Current-state tables are copied whole into dated snapshot folders
  (last 7 kept, so you can compare runs); append-only history (trip events, ledger entries)
  is extracted incrementally from a saved id watermark (`lake/_state.json`).
* **Types preserved.** DuckDB's PostgreSQL connector copies exact types: decimals stay
  decimals (money), timestamps keep their time zone, arrays stay arrays.
* **IST everywhere in reports.** Timestamps are stored in UTC; dates and hours in the models
  are Indian Standard Time.
* **Tests as contracts** (`dbt build` fails if any fail): unique/not-null keys, valid statuses
  and services, referential integrity, and business rules: every ledger transaction sums to
  zero, fares add up (driver + commission + fees + GST − discount), no negative money,
  completed trips are priced, trip timelines are in order, parcels were delivered with the code.

## Storage

Small: the lake is a few MB per snapshot (Parquet compresses 5–10×), the warehouse tens of MB.
Everything under `lake/`, `warehouse/` and `.dagster/` is rebuilt by the pipeline and is
git-ignored.

## Next (Part B, needs Docker)

Streaming change data capture (Debezium → Kafka) instead of batch snapshots, live demand per
zone, Superset dashboards, and demand/ETA forecasting models trained on `core.fct_trips`.
