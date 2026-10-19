"""Monthly CO₂ report for company clients (for their ESG / sustainability reporting).

For every completed business trip in the month: distance, the vehicle's grams of CO₂ per km
(electric vehicles count the grid's share), the emissions, and the saving against each employee
driving their own petrol car alone. Totals by ride type, the electric share of km, the trend over
six months, and a CSV the company can hand to its auditors. Estimates, labelled as such, using the
same factors as the rider eco score.
"""

import csv
import io
from collections import defaultdict
from datetime import datetime

from django.utils import timezone

from apps.core.conf import eco_terms


def _month_bounds(month: str | None):
    now = timezone.localtime()
    if month:
        year, mon = (int(x) for x in month.split("-"))
    else:
        year, mon = now.year, now.month
    start = timezone.make_aware(datetime(year, mon, 1))
    end = timezone.make_aware(datetime(year + (mon == 12), mon % 12 + 1, 1))
    return start, end


def _trip_rows(profile, start, end):
    from apps.rides import eco
    from apps.rides.models import TripStatus

    baseline = eco_terms()["baseline"]
    trips = profile.trips.filter(
        status=TripStatus.COMPLETED, completed_at__gte=start, completed_at__lt=end
    ).select_related("vehicle", "ride_type", "rider__user")
    for t in trips:
        km = float(t.actual_distance_km or t.estimated_distance_km or 0)
        g = eco.grams_per_km(t)
        electric = bool(t.vehicle and t.vehicle.fuel_type == "EV")
        yield {
            "trip": t.trip_number,
            "date": timezone.localtime(t.completed_at).date(),
            "employee": t.rider.user.get_full_name(),
            "ride_type": t.ride_type.name,
            "electric": electric,
            "km": round(km, 2),
            "co2_kg": round(km * g / 1000, 3),
            "saved_kg": round(km * max(0, baseline - g) / 1000, 3),
        }


def report(profile, *, month: str | None = None) -> dict:
    start, end = _month_bounds(month)
    rows = list(_trip_rows(profile, start, end))
    by_type = defaultdict(lambda: {"trips": 0, "km": 0.0, "co2_kg": 0.0})
    for r in rows:
        b = by_type[r["ride_type"] + (" (electric)" if r["electric"] else "")]
        b["trips"] += 1
        b["km"] += r["km"]
        b["co2_kg"] += r["co2_kg"]
    km = sum(r["km"] for r in rows)
    ev_km = sum(r["km"] for r in rows if r["electric"])
    trend = []
    for back in range(5, -1, -1):
        y, m = start.year, start.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        s, e = _month_bounds(f"{y}-{m:02d}")
        month_rows = list(_trip_rows(profile, s, e))
        trend.append(
            {
                "month": f"{y}-{m:02d}",
                "co2_kg": round(sum(r["co2_kg"] for r in month_rows), 1),
                "km": round(sum(r["km"] for r in month_rows), 1),
            }
        )
    return {
        "company": profile.name,
        "month": f"{start:%Y-%m}",
        "trips": len(rows),
        "km": round(km, 1),
        "co2_kg": round(sum(r["co2_kg"] for r in rows), 1),
        "saved_kg": round(sum(r["saved_kg"] for r in rows), 1),
        "electric_share_pct": round(100 * ev_km / km) if km else 0,
        "grams_per_km": round(1000 * sum(r["co2_kg"] for r in rows) / km) if km else 0,
        "by_ride_type": [
            {
                "ride_type": k,
                "trips": v["trips"],
                "km": round(v["km"], 1),
                "co2_kg": round(v["co2_kg"], 1),
            }
            for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["co2_kg"])
        ],
        "trend": trend,
        "method": "Estimate: grams of CO₂ per km by vehicle type (electric vehicles at the "
        "grid's share), saving measured against a private petrol car carrying one person.",
    }


def csv_export(profile, *, month: str | None = None) -> tuple[bytes, str]:
    start, end = _month_bounds(month)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        ["trip", "date", "employee", "ride_type", "electric", "km", "co2_kg", "saved_vs_own_car_kg"]
    )
    for r in _trip_rows(profile, start, end):
        w.writerow(
            [
                r["trip"],
                r["date"],
                r["employee"],
                r["ride_type"],
                "yes" if r["electric"] else "no",
                r["km"],
                r["co2_kg"],
                r["saved_kg"],
            ]
        )
    return (
        out.getvalue().encode(),
        f"co2-{profile.name.lower().replace(' ', '-')}-{start:%Y-%m}.csv",
    )
