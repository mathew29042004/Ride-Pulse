"""Metro first and last mile: for longer trips in metro cities, a ride to the nearest station,
the metro, and a ride from the exit station, often cheaper and, at peak hours, faster.

* ``plan()`` finds stations near the pickup and drop (within 4 km), on the same line or joined
  at an interchange, prices both rides and the metro ticket, estimates the time, and compares
  it with a direct ride. It's only offered for trips of 8 km or more that save money.
* Booking it requests the first ride now and schedules the last-mile ride for when the metro
  should reach the exit station. Tapping "I'm at the station" sends that ride straight away.
* Metro timings and fares are estimates (34 km/h between stations, 4 minutes' wait, 5 per change;
  fares by distance in each city's slabs), shown as such.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.geo.distance import haversine_km

# city slug: {line: [(station, lat, lng), ...]} (a representative set of stations per line)
LINES = {
    "chennai": {
        "Blue": [
            ("Chennai Airport", 12.9809, 80.1640),
            ("Alandur", 13.0040, 80.2010),
            ("Guindy", 13.0090, 80.2130),
            ("Saidapet", 13.0230, 80.2280),
            ("Teynampet", 13.0360, 80.2470),
            ("Thousand Lights", 13.0580, 80.2530),
            ("Government Estate", 13.0700, 80.2700),
            ("Chennai Central", 13.0820, 80.2750),
            ("Washermanpet", 13.1100, 80.2850),
        ],
        "Green": [
            ("St. Thomas Mount", 12.9950, 80.1990),
            ("Alandur", 13.0040, 80.2010),
            ("Ashok Nagar", 13.0360, 80.2120),
            ("Vadapalani", 13.0500, 80.2120),
            ("Koyambedu", 13.0700, 80.2050),
            ("Anna Nagar Tower", 13.0850, 80.2080),
            ("Kilpauk", 13.0780, 80.2420),
            ("Egmore", 13.0790, 80.2610),
            ("Chennai Central", 13.0820, 80.2750),
        ],
    },
    "bengaluru": {
        "Purple": [
            ("Whitefield", 12.9950, 77.7580),
            ("KR Puram", 13.0000, 77.6780),
            ("Indiranagar", 12.9780, 77.6390),
            ("MG Road", 12.9750, 77.6060),
            ("Majestic", 12.9760, 77.5720),
            ("Vijayanagar", 12.9710, 77.5370),
            ("Mysore Road", 12.9470, 77.5300),
            ("Kengeri", 12.9080, 77.4870),
        ],
        "Green": [
            ("Nagasandra", 13.0480, 77.5000),
            ("Yeshwanthpur", 13.0230, 77.5500),
            ("Majestic", 12.9760, 77.5720),
            ("Lalbagh", 12.9500, 77.5850),
            ("Jayanagar", 12.9300, 77.5800),
            ("Banashankari", 12.9150, 77.5730),
            ("Silk Institute", 12.8620, 77.5300),
        ],
    },
    "kochi": {
        "Blue": [
            ("Aluva", 10.1100, 76.3500),
            ("Kalamassery", 10.0500, 76.3200),
            ("Edappally", 10.0250, 76.3080),
            ("Palarivattom", 10.0060, 76.3060),
            ("Kaloor", 9.9970, 76.2990),
            ("MG Road", 9.9800, 76.2830),
            ("Ernakulam South", 9.9690, 76.2900),
            ("Vyttila", 9.9680, 76.3200),
            ("Tripunithura", 9.9500, 76.3500),
        ],
    },
}
FARE_SLABS = {  # (up to km, ₹)
    "chennai": [(2, 10), (5, 20), (12, 30), (21, 40), (999, 50)],
    "bengaluru": [(2, 10), (4, 20), (6, 30), (8, 40), (10, 50), (999, 60)],
    "kochi": [(2, 10), (5, 20), (10, 30), (15, 40), (20, 50), (999, 60)],
}
NEAR_KM, MIN_TRIP_KM = 4.0, 8.0
SPEED_KMH, WAIT_MIN, CHANGE_MIN = 34, 4, 5


def _stations(city_slug):
    for line, stops in LINES.get(city_slug, {}).items():
        for i, (name, lat, lng) in enumerate(stops):
            yield line, i, name, lat, lng


def _nearest(city_slug, lat, lng):
    best = None
    for line, i, name, slat, slng in _stations(city_slug):
        km = haversine_km(lat, lng, slat, slng)
        if km <= NEAR_KM and (best is None or km < best["km"]):
            best = {"line": line, "index": i, "name": name, "lat": slat, "lng": slng, "km": km}
    return best


def _metro_km(city_slug, a, b) -> tuple[float, int] | None:
    """Track km and number of changes between two stations (same line, or one interchange)."""
    lines = LINES[city_slug]

    def along(line, i, j):
        stops = lines[line]
        lo, hi = sorted((i, j))
        return sum(
            haversine_km(stops[k][1], stops[k][2], stops[k + 1][1], stops[k + 1][2]) * 1.15
            for k in range(lo, hi)
        )

    if a["line"] == b["line"]:
        return along(a["line"], a["index"], b["index"]), 0
    names_a = {s[0]: i for i, s in enumerate(lines[a["line"]])}
    for j, (name, *_rest) in enumerate(lines[b["line"]]):
        if name in names_a:  # interchange
            return along(a["line"], a["index"], names_a[name]) + along(b["line"], j, b["index"]), 1
    return None


def metro_fare(city_slug: str, km: float) -> Decimal:
    return Decimal(next(f for upto, f in FARE_SLABS[city_slug] if km <= upto))


def plan(*, city, pickup, dropoff, ride_type, at=None) -> dict | None:
    from apps.pricing import services as pricing

    at = at or timezone.now()
    if city.slug not in LINES or haversine_km(*pickup, *dropoff) < MIN_TRIP_KM:
        return None
    entry, exit_ = _nearest(city.slug, *pickup), _nearest(city.slug, *dropoff)
    if not entry or not exit_ or entry["name"] == exit_["name"]:
        return None
    track = _metro_km(city.slug, entry, exit_)
    if track is None:
        return None
    km, changes = track
    first = pricing.estimate_fare(
        city=city, ride_type=ride_type, pickup=pickup, dropoff=(entry["lat"], entry["lng"]), at=at
    )
    metro_minutes = km / SPEED_KMH * 60 + WAIT_MIN + CHANGE_MIN * changes
    reach_exit = at + timedelta(
        minutes=float(first.route.duration_minutes) + 6 + metro_minutes
    )  # 6: walk & ticket
    last = pricing.estimate_fare(
        city=city,
        ride_type=ride_type,
        pickup=(exit_["lat"], exit_["lng"]),
        dropoff=dropoff,
        at=reach_exit,
    )
    direct = pricing.estimate_fare(
        city=city, ride_type=ride_type, pickup=pickup, dropoff=dropoff, at=at
    )
    ticket = metro_fare(city.slug, km)
    total = first.fare.total + ticket + last.fare.total
    minutes = (reach_exit - at).total_seconds() / 60 + 3 + float(last.route.duration_minutes)
    if total >= direct.fare.total:
        return None
    return {
        "entry": {k: entry[k] for k in ("name", "line", "lat", "lng")},
        "exit": {k: exit_[k] for k in ("name", "line", "lat", "lng")},
        "changes": changes,
        "metro_km": round(km, 1),
        "metro_fare": ticket,
        "first_fare": first.fare.total,
        "last_fare": last.fare.total,
        "total": total,
        "minutes": round(minutes),
        "direct_fare": direct.fare.total,
        "direct_minutes": round(float(direct.route.duration_minutes)),
        "saves": direct.fare.total - total,
        "reach_exit_at": reach_exit,
        "estimate": True,
    }


def book(*, rider, ride_type, pickup, dropoff, dropoff_address: str, payment_method: str, now=None):
    """The first ride now; the last-mile ride scheduled for when the metro reaches the exit."""
    from apps.geo.services import require_city
    from apps.pricing import services as pricing

    from . import services as rides
    from .models import ScheduledRide

    now = now or timezone.now()
    city = require_city(*pickup)
    p = plan(city=city, pickup=pickup, dropoff=dropoff, ride_type=ride_type, at=now)
    if p is None:
        raise BusinessRuleViolation("Metro + ride isn't a better option for this trip.")
    first = rides.request_trip(
        rider=rider,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=(p["entry"]["lat"], p["entry"]["lng"]),
        dropoff_address=f"{p['entry']['name']} metro station",
        payment_method=payment_method,
        now=now,
    )
    exit_point = (p["exit"]["lat"], p["exit"]["lng"])
    estimate = pricing.estimate_fare(
        city=city, ride_type=ride_type, pickup=exit_point, dropoff=dropoff, at=p["reach_exit_at"]
    )
    last = ScheduledRide.objects.create(
        rider=rider,
        ride_type=ride_type,
        city=city,
        pickup_lat=exit_point[0],
        pickup_lng=exit_point[1],
        pickup_address=f"{p['exit']['name']} metro station",
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        dropoff_address=dropoff_address[:255],
        payment_method=payment_method,
        scheduled_for=p["reach_exit_at"],
        quoted_fare=estimate.fare.total,
        metro_trip=first,
    )
    return first, last, p


def at_station(ride, *, now=None):
    """The rider has reached the exit station: send the last-mile ride now."""
    from .models import ScheduledRideStatus

    now = now or timezone.now()
    if ride.status != ScheduledRideStatus.SCHEDULED or ride.metro_trip_id is None:
        raise BusinessRuleViolation("This ride has already been sent.")
    from .models import TERMINAL_STATUSES

    if ride.metro_trip.status not in TERMINAL_STATUSES:
        raise BusinessRuleViolation("Your ride to the station hasn't finished yet.")
    ride.scheduled_for = now
    ride.save(update_fields=["scheduled_for", "updated_at"])
    from . import services as rides

    rides.dispatch_scheduled_rides(now=now)
    ride.refresh_from_db()
    return ride
