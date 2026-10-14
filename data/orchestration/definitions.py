"""Dagster: the Ride Pulse data pipeline as software-defined assets.

    lake/*  (extract.py: Postgres -> Parquet, one asset per table)
      -> dbt staging -> core star schema -> reporting tables (with data-quality tests)
        -> insights_report (Markdown summary)

A schedule refreshes everything daily at 02:00 IST. Run the UI with ``make data-ui``.
"""

from pathlib import Path

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Definitions,
    MaterializeResult,
    ScheduleDefinition,
    asset,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets
from pipeline import extract as extract_module
from pipeline import report as report_module

DATA_DIR = Path(__file__).resolve().parent.parent
DBT_DIR = DATA_DIR / "dbt"

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()

LAKE_TABLES = [t.name for t in extract_module.TABLES]


@multi_asset(
    specs=[
        AssetSpec(
            AssetKey(["lake", name]),
            group_name="extract",
            description=f"Privacy-filtered Parquet copy of the app's {name}",
        )
        for name in LAKE_TABLES
    ],
    can_subset=False,
)
def lake(context: AssetExecutionContext):
    """Extract every table from PostgreSQL into the Parquet lake (snapshots + increments)."""
    written = extract_module.extract(log=context.log.info)
    for name in LAKE_TABLES:
        yield MaterializeResult(
            asset_key=AssetKey(["lake", name]), metadata={"rows": written.get(name, 0)}
        )


@dbt_assets(manifest=dbt_project.manifest_path)
def warehouse(context: AssetExecutionContext, dbt: DbtCliResource):
    """dbt models (staging, core, reporting) and their data-quality tests, in DuckDB."""
    # dbt runs relative paths (lake, warehouse) from its project folder.
    yield from dbt.cli(["build"], context=context).stream()


@asset(
    deps=[
        AssetKey("rpt_city_daily"),
        AssetKey("rpt_service_mix"),
        AssetKey("rpt_hourly_demand"),
        AssetKey("rpt_cancellations"),
        AssetKey("rpt_driver_weekly"),
        AssetKey("rpt_support_sla"),
        AssetKey("rpt_org_coverage"),
    ],
    group_name="insights",
)
def insights_report(context: AssetExecutionContext) -> MaterializeResult:
    """The Markdown insights summary in data/reports/insights.md."""
    path = report_module.build(log=context.log.info)
    return MaterializeResult(metadata={"path": str(path), "preview": path.read_text()[:2000]})


daily_refresh = define_asset_job("daily_refresh", selection=AssetSelection.all())

defs = Definitions(
    assets=[lake, warehouse, insights_report],
    jobs=[daily_refresh],
    schedules=[
        ScheduleDefinition(
            job=daily_refresh, cron_schedule="0 2 * * *", execution_timezone="Asia/Kolkata"
        )
    ],
    resources={
        "dbt": DbtCliResource(
            project_dir=dbt_project, dbt_executable=str(DATA_DIR / ".venv" / "bin" / "dbt")
        )
    },
)
