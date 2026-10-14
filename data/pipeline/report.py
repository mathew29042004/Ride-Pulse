"""Insights report: a readable summary of the warehouse, written after every pipeline run to
``data/reports/insights.md``."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

DATA_DIR = Path(__file__).resolve().parent.parent
WAREHOUSE = DATA_DIR / "warehouse" / "ridepulse.duckdb"
REPORT = DATA_DIR / "reports" / "insights.md"
# Machine-readable summary for the ops console's "Data insights" page.
SUMMARY = DATA_DIR / "reports" / "insights.json"


def _rupees(value) -> str:
    value = float(value or 0)
    if value >= 1e7:
        return f"₹{value / 1e7:.2f} crore"
    if value >= 1e5:
        return f"₹{value / 1e5:.2f} lakh"
    return f"₹{value:,.0f}"


def _table(con, sql: str, headers: list[str]) -> list[str]:
    rows = con.execute(sql).fetchall()
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return out


def build(log=print) -> Path:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    total = con.execute(
        """
        select count(*), count(*) filter (where is_completed),
               sum(fare_total), sum(platform_commission), sum(driver_earning + tip_amount),
               count(distinct city_id), min(request_date), max(request_date),
               count(*) filter (where service = 'PARCEL'),
               sum(co2_saved_g) / 1e6
        from core.fct_trips
        """
    ).fetchone()
    trips, completed, gross, commission, driver_pay, cities, first, last, parcels, co2_t = total
    lines = [
        "# Ride Pulse insights",
        "",
        f"_Generated {datetime.now(UTC):%d %b %Y %H:%M} UTC from {first} to {last} "
        f"(IST dates). Simulated data: patterns are realistic, the numbers are not real._",
        "",
        "## Headline",
        "",
        f"- **{trips:,} trip requests** in **{cities} cities**, **{completed:,} completed** "
        f"({completed / max(trips, 1):.0%} completion).",
        f"- **{_rupees(gross)} gross bookings**: {_rupees(driver_pay)} to drivers (incl. tips), "
        f"{_rupees(commission)} Ride Pulse commission.",
        f"- **{parcels:,} parcel deliveries** ({parcels / max(trips, 1):.1%} of requests).",
        f"- **{co2_t:.2f} tonnes of CO₂ saved** versus everyone driving their own car.",
        "",
        "## Top cities by gross bookings",
        "",
        *_table(
            con,
            """
            select city, state, sum(requests), sum(completed),
                   round(sum(completed) / sum(requests) * 100, 1) || '%',
                   '₹' || format('{:,.0f}', sum(gross_bookings))
            from reporting.rpt_city_daily group by all order by sum(gross_bookings) desc limit 10
            """,
            ["City", "State", "Requests", "Completed", "Completion", "Gross bookings"],
        ),
        "",
        "## By state and service",
        "",
        *_table(
            con,
            """
            select state, service, sum(requests), sum(completed),
                   '₹' || format('{:,.0f}', sum(gross_bookings)), round(avg(avg_fare), 0)
            from reporting.rpt_service_mix group by all order by state, sum(requests) desc
            """,
            ["State", "Service", "Requests", "Completed", "Gross bookings", "Avg fare (₹)"],
        ),
        "",
        "## Busiest hours (IST, all cities)",
        "",
        *_table(
            con,
            """
            select hour || ':00', sum(requests), round(avg(avg_surge), 2),
                   round(avg(no_driver_rate) * 100, 1) || '%'
            from reporting.rpt_hourly_demand group by hour order by sum(requests) desc limit 6
            """,
            ["Hour", "Requests", "Avg surge", "No driver found"],
        ),
        "",
        "## Where riders were left without a driver",
        "",
        *_table(
            con,
            """
            select city, ride_type, requests, no_driver,
                   round(no_driver / requests * 100, 1) || '%'
            from reporting.rpt_cancellations
            where requests >= 30 order by no_driver / requests desc limit 8
            """,
            ["City", "Ride type", "Requests", "No driver", "Rate"],
        ),
        "",
        "## Driver earnings per online hour (median, by vehicle)",
        "",
        *_table(
            con,
            """
            select vehicle_class, case when is_electric then 'EV' else 'Fuel' end,
                   count(distinct driver_id), round(median(earnings_per_hour), 0),
                   round(median(trips), 1)
            from reporting.rpt_driver_weekly
            where earnings_per_hour is not null and vehicle_class is not null
            group by all order by 1, 2
            """,
            ["Vehicle", "Fuel", "Drivers", "₹ per online hour", "Trips per week"],
        ),
        "",
        "## Support",
        "",
        *_table(
            con,
            """
            select category, sum(tickets), sum(resolved),
                   round(sum(within_sla) / nullif(sum(resolved), 0) * 100, 0) || '%',
                   round(avg(avg_hours_to_resolve), 1)
            from reporting.rpt_support_sla group by all order by sum(tickets) desc
            """,
            ["Category", "Tickets", "Resolved", "Within SLA", "Avg hours to resolve"],
        ),
        "",
        "## Team coverage (driver partners per fleet executive)",
        "",
        *_table(
            con,
            """
            select state, sum(approved_drivers), sum(fleet_executives),
                   round(sum(approved_drivers) / nullif(sum(fleet_executives), 0), 1),
                   sum(support_staff)
            from reporting.rpt_org_coverage group by state order by 2 desc
            """,
            ["State", "Drivers", "Fleet executives", "Drivers per executive", "Support staff"],
        ),
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    SUMMARY.write_text(json.dumps(summary(con), indent=1, default=_json_value))
    log(f"Wrote {REPORT} and {SUMMARY.name}")
    return REPORT


def _json_value(value):
    """Numbers stay numbers (DuckDB sums are Decimal); dates become ISO strings."""
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _rows(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def summary(con) -> dict:
    """The numbers behind the report, as JSON for the ops console."""
    (headline,) = _rows(
        con,
        """
        select count(*) as requests, count(*) filter (where is_completed) as completed,
               sum(fare_total) as gross_bookings, sum(platform_commission) as commission,
               sum(driver_earning + tip_amount) as driver_earnings,
               count(distinct city_id) as cities, min(request_date) as first_day,
               max(request_date) as last_day,
               count(*) filter (where service = 'PARCEL') as parcels,
               round(sum(co2_saved_g) / 1e6, 2) as co2_saved_tonnes
        from core.fct_trips
        """,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "headline": headline,
        "daily": _rows(
            con,
            """
            select request_date as date, sum(requests) as requests, sum(completed) as completed,
                   sum(gross_bookings) as gross_bookings, sum(parcels) as parcels
            from reporting.rpt_city_daily group by 1 order by 1
            """,
        ),
        "cities": _rows(
            con,
            """
            select city, state, sum(requests) as requests, sum(completed) as completed,
                   round(sum(completed) / sum(requests), 3) as completion_rate,
                   sum(gross_bookings) as gross_bookings, round(avg(avg_pickup_minutes), 1)
                   as avg_pickup_minutes
            from reporting.rpt_city_daily group by all order by gross_bookings desc
            """,
        ),
        "states": _rows(
            con,
            """
            select state, service, sum(requests) as requests, sum(completed) as completed,
                   sum(gross_bookings) as gross_bookings
            from reporting.rpt_service_mix group by all order by state, requests desc
            """,
        ),
        "hours": _rows(
            con,
            """
            select hour, sum(requests) as requests, round(avg(avg_surge), 2) as avg_surge,
                   round(avg(no_driver_rate), 3) as no_driver_rate
            from reporting.rpt_hourly_demand group by hour order by hour
            """,
        ),
        "no_driver_hotspots": _rows(
            con,
            """
            select city, ride_type, requests, no_driver,
                   round(no_driver / requests, 3) as rate
            from reporting.rpt_cancellations where requests >= 30
            order by no_driver / requests desc limit 10
            """,
        ),
        "driver_earnings": _rows(
            con,
            """
            select vehicle_class, case when is_electric then 'EV' else 'Fuel' end as fuel,
                   count(distinct driver_id) as drivers,
                   round(median(earnings_per_hour), 0) as median_per_hour,
                   round(median(trips), 1) as median_trips_per_week
            from reporting.rpt_driver_weekly
            where earnings_per_hour is not null and vehicle_class is not null
            group by all order by 1, 2
            """,
        ),
        "support": _rows(
            con,
            """
            select category, sum(tickets) as tickets, sum(resolved) as resolved,
                   sum(within_sla) as within_sla, round(avg(avg_hours_to_resolve), 1)
                   as avg_hours_to_resolve
            from reporting.rpt_support_sla group by all order by tickets desc
            """,
        ),
        "team": _rows(
            con,
            """
            select state, sum(approved_drivers) as drivers, sum(fleet_executives)
                   as fleet_executives, sum(support_staff) as support_staff,
                   sum(city_managers) as city_managers
            from reporting.rpt_org_coverage group by state order by drivers desc
            """,
        ),
    }


if __name__ == "__main__":
    build()
