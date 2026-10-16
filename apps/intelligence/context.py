"""Weather and city events: the outside world that moves ride demand.

* **Weather** comes from Open-Meteo (free, no API key), refreshed every 30 minutes per city. If
  the network is unavailable, a seasonal simulation stands in (the north-east monsoon brings
  October-December rain to Tamil Nadu and coastal Andhra; the south-west monsoon, June-September,
  to Kerala and coastal Karnataka) and each reading says which source it came from.
* **Events** (matches, concerts, festivals) are added by ops. Riders pour in before an event
  starts and out when it ends.
* Both feed the next-hour demand forecast (and so driver nudges), the simulator's request rate,
  and the alerts riders and drivers see. Surge needs no extra rule: it already follows demand.
"""

import hashlib
import math
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.utils import timezone

from apps.geo.distance import haversine_km
from apps.geo.models import City

from .models import CityEvent, WeatherReading

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
FRESH_FOR = timedelta(hours=2)
EVENT_RADIUS_KM = 3.0
RIDE_SHARE_OF_CROWD = 0.012  # share of the crowd booking a ride in the peak hour
WMO = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    51: "Drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    80: "Showers",
    81: "Heavy showers",
    82: "Violent showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
}
NE_MONSOON = {"Tamil Nadu", "Andhra Pradesh"}
SW_MONSOON = {"Kerala", "Karnataka"}


def _fetch(city: City) -> dict | None:
    try:
        response = requests.get(
            OPEN_METEO,
            params={
                "latitude": city.center_lat,
                "longitude": city.center_lng,
                "current": "temperature_2m,precipitation,weather_code",
                "hourly": "precipitation_probability",
                "forecast_hours": 3,
                "timezone": "Asia/Kolkata",
            },
            timeout=4,
        )
        response.raise_for_status()
        data = response.json()
        current = data["current"]
        chance = max(data.get("hourly", {}).get("precipitation_probability") or [0])
        return {
            "temperature_c": Decimal(str(current["temperature_2m"])),
            "rain_mm": Decimal(str(current.get("precipitation") or 0)),
            "rain_chance_next_3h": int(chance or 0),
            "condition": WMO.get(int(current.get("weather_code", 0)), "Cloudy"),
            "source": "open-meteo",
        }
    except Exception:  # offline, rate-limited, or a changed response: simulate instead
        return None


def _simulate(city: City, at: datetime) -> dict:
    """Deterministic seasonal weather for a city and hour (same input, same weather)."""
    local = timezone.localtime(at)
    seed = int(hashlib.sha256(f"{city.slug}:{local:%Y%m%d%H}".encode()).hexdigest(), 16)
    roll = (seed % 1000) / 1000
    month = local.month
    wet = (city.state in NE_MONSOON and month in (10, 11, 12)) or (
        city.state in SW_MONSOON and month in (6, 7, 8, 9)
    )
    # Monsoon rain clusters in the afternoon and evening.
    afternoon = 14 <= local.hour <= 21
    chance = (0.45 if wet else 0.08) * (1.4 if afternoon else 0.8)
    raining = roll < chance
    rain = round(0.5 + 9 * (chance - roll) / max(chance, 0.01), 1) if raining else 0.0
    temperature = 27 + 5 * math.sin((local.hour - 9) / 24 * 2 * math.pi) - (2 if raining else 0)
    condition = (
        "Heavy rain"
        if rain >= 4
        else "Rain"
        if rain >= 1
        else "Light rain"
        if raining
        else ("Partly cloudy" if wet else "Clear")
    )
    return {
        "temperature_c": Decimal(str(round(temperature, 1))),
        "rain_mm": Decimal(str(rain)),
        "rain_chance_next_3h": min(100, int(chance * 100 + (30 if raining else 0))),
        "condition": condition,
        "source": "simulated",
    }


def refresh_weather(*, now: datetime | None = None, live: bool = True) -> dict:
    now = now or timezone.now()
    counts = {"open-meteo": 0, "simulated": 0}
    offline = not live
    for city in City.objects.filter(is_active=True):
        reading = None if offline else _fetch(city)
        if reading is None:
            offline = True  # don't wait on 33 timeouts once the network is clearly down
            reading = _simulate(city, now)
        WeatherReading.objects.create(city=city, observed_at=now, **reading)
        counts[reading["source"]] += 1
    # Weather isn't personal data; a year of it trains the models (ETA, demand).
    WeatherReading.objects.filter(observed_at__lt=now - timedelta(days=400)).delete()
    return counts


def current_weather(city_id: int, *, now: datetime | None = None) -> WeatherReading | None:
    now = now or timezone.now()
    return (
        WeatherReading.objects.filter(city_id=city_id, observed_at__gte=now - FRESH_FOR)
        .order_by("-observed_at")
        .first()
    )


def weather_factor(reading: WeatherReading | None) -> float:
    """How much rain lifts demand (people who'd walk or ride a scooter book a cab)."""
    if reading is None:
        return 1.0
    rain = float(reading.rain_mm)
    if rain >= 4:
        return 1.4
    if rain >= 1:
        return 1.25
    if rain > 0 or reading.rain_chance_next_3h >= 60:
        return 1.1
    return 1.0


def events_in_window(start: datetime, end: datetime, *, city_id: int | None = None):
    """Events whose arrival (90 min before the start) or exit (30 min before to 90 min after
    the end) overlaps [start, end)."""
    events = CityEvent.objects.filter(
        starts_at__lt=end + timedelta(minutes=90), ends_at__gt=start - timedelta(minutes=90)
    )
    if city_id:
        events = events.filter(city_id=city_id)
    return events


def event_extra_trips(zone, hour_start: datetime) -> tuple[float, list[str]]:
    """Extra trips expected in a zone in the hour from ``hour_start`` because of events."""
    hour_end = hour_start + timedelta(hours=1)
    extra, reasons = 0.0, []
    for event in events_in_window(hour_start, hour_end, city_id=zone.city_id):
        if haversine_km(zone.center_lat, zone.center_lng, event.lat, event.lng) > EVENT_RADIUS_KM:
            continue
        leaving = (
            event.ends_at - timedelta(minutes=30) < hour_end
            and event.ends_at + timedelta(minutes=90) > hour_start
        )
        arriving = (
            event.starts_at - timedelta(minutes=90) < hour_end and event.starts_at > hour_start
        )
        if leaving:
            extra += event.expected_attendance * RIDE_SHARE_OF_CROWD
            reasons.append(f"{event.name} ends {timezone.localtime(event.ends_at):%I:%M %p}")
        elif arriving:
            extra += event.expected_attendance * RIDE_SHARE_OF_CROWD * 0.5
            reasons.append(f"{event.name} starts {timezone.localtime(event.starts_at):%I:%M %p}")
    return extra, reasons


def for_rider(lat: float, lng: float, *, now: datetime | None = None) -> dict:
    """What the rider app shows on Home: rain, and big events near them today."""
    from apps.geo.services import city_for_point

    now = now or timezone.now()
    city = city_for_point(lat, lng)
    if city is None:
        return {"weather": None, "events": [], "messages": []}
    reading = current_weather(city.pk, now=now)
    local_end = timezone.localtime(now).replace(hour=23, minute=59)
    events = [
        e
        for e in CityEvent.objects.filter(city=city, ends_at__gte=now, starts_at__lte=local_end)
        if haversine_km(lat, lng, e.lat, e.lng) <= 8
    ]
    messages = []
    if reading and weather_factor(reading) >= 1.25:
        messages.append(
            f"{reading.condition} in {city.name}: rides are in demand, so book a little early."
        )
    elif reading and weather_factor(reading) > 1:
        messages.append(f"Rain likely in {city.name} in the next few hours.")
    for e in events:
        messages.append(
            f"{e.name} at {e.venue} ends around {timezone.localtime(e.ends_at):%I:%M %p}: expect "
            "traffic and higher demand nearby."
        )
    return {
        "weather": {
            "condition": reading.condition,
            "temperature_c": str(reading.temperature_c),
            "rain_mm": str(reading.rain_mm),
            "rain_chance_next_3h": reading.rain_chance_next_3h,
            "source": reading.source,
        }
        if reading
        else None,
        "events": [
            {
                "name": e.name,
                "venue": e.venue,
                "starts_at": e.starts_at.isoformat(),
                "ends_at": e.ends_at.isoformat(),
            }
            for e in events
        ],
        "messages": messages,
    }


def overview(*, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    latest = {}
    for reading in WeatherReading.objects.filter(observed_at__gte=now - FRESH_FOR).select_related(
        "city"
    ):
        if (
            reading.city_id not in latest
            or reading.observed_at > latest[reading.city_id].observed_at
        ):
            latest[reading.city_id] = reading
    rows = sorted(latest.values(), key=lambda r: (-float(r.rain_mm), r.city.name))
    upcoming = CityEvent.objects.filter(
        ends_at__gte=now, starts_at__lte=now + timedelta(days=14)
    ).select_related("city")
    return {
        "weather": [
            {
                "city": r.city.name,
                "condition": r.condition,
                "temperature_c": str(r.temperature_c),
                "rain_mm": str(r.rain_mm),
                "rain_chance_next_3h": r.rain_chance_next_3h,
                "demand_factor": weather_factor(r),
                "source": r.source,
                "observed_at": r.observed_at.isoformat(),
            }
            for r in rows
        ],
        "events": [
            {
                "id": e.pk,
                "name": e.name,
                "kind": e.get_kind_display(),
                "city": e.city.name,
                "venue": e.venue,
                "starts_at": e.starts_at.isoformat(),
                "ends_at": e.ends_at.isoformat(),
                "expected_attendance": e.expected_attendance,
                "peak_extra_trips": round(e.expected_attendance * RIDE_SHARE_OF_CROWD),
            }
            for e in upcoming
        ],
    }


ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def _archive(city: City, start, end) -> dict | None:
    """Hourly rain and temperature for a past date range (Open-Meteo's historical archive)."""
    try:
        response = requests.get(
            ARCHIVE,
            params={
                "latitude": city.center_lat,
                "longitude": city.center_lng,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": "temperature_2m,precipitation,weather_code",
                "timezone": "Asia/Kolkata",
            },
            timeout=8,
        )
        response.raise_for_status()
        return response.json()["hourly"]
    except Exception:
        return None


def backfill(*, days: int = 60, now: datetime | None = None, live: bool = True) -> dict:
    """Hourly weather history for every city (archive, or the seasonal simulation offline)."""
    now = now or timezone.now()
    end = timezone.localdate(now) - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    counts = {"open-meteo": 0, "simulated": 0}
    offline = not live
    for city in City.objects.filter(is_active=True):
        first = timezone.make_aware(datetime.combine(start, datetime.min.time()))
        last = timezone.make_aware(datetime.combine(end, datetime.max.time()))
        WeatherReading.objects.filter(
            city=city, observed_at__gte=first, observed_at__lte=last
        ).delete()
        hourly = None if offline else _archive(city, start, end)
        rows = []
        if hourly:
            for at, temp, rain, code in zip(
                hourly["time"],
                hourly["temperature_2m"],
                hourly["precipitation"],
                hourly["weather_code"],
                strict=False,
            ):
                rows.append(
                    WeatherReading(
                        city=city,
                        observed_at=timezone.make_aware(datetime.fromisoformat(at)),
                        temperature_c=Decimal(str(temp or 0)),
                        rain_mm=Decimal(str(rain or 0)),
                        rain_chance_next_3h=100 if (rain or 0) > 0 else 0,
                        condition=WMO.get(int(code or 0), "Cloudy"),
                        source="open-meteo",
                    )
                )
        else:
            offline = True
            at = first
            while at <= last:
                rows.append(WeatherReading(city=city, observed_at=at, **_simulate(city, at)))
                at += timedelta(hours=1)
        WeatherReading.objects.bulk_create(rows, batch_size=2000)
        counts[rows[0].source if rows else "simulated"] += len(rows)
    return counts
