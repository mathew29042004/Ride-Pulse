"""Driver safety scoring ("Pulse safety score").

The driver app reports telemetry with every completed trip. Each trip gets a 0–100 score from
four behaviours, each normalised so a long trip isn't punished for having more events than a
short one:

* harsh braking and harsh acceleration, per 100 km
* share of driving time spent over the speed limit
* share of distance driven at night (23:00–05:00), when accident risk per km is highest

A driver's score is the distance-weighted mean of their recent trips, so one short bad trip
can't swamp weeks of good driving. Dispatch prefers safer drivers when ETAs are close.
"""

from collections.abc import Iterable
from dataclasses import dataclass

MAX_BRAKING_PENALTY = 30.0
MAX_ACCEL_PENALTY = 20.0
MAX_SPEEDING_PENALTY = 35.0
MAX_NIGHT_PENALTY = 15.0

BRAKING_POINTS_PER_EVENT_PER_100KM = 4.0
ACCEL_POINTS_PER_EVENT_PER_100KM = 2.5
SPEEDING_POINTS_PER_PERCENT = 1.2
NIGHT_POINTS_PER_PERCENT = 0.25

MIN_TRIPS_FOR_SCORE = 5
MIN_DISTANCE_FOR_SCORE_KM = 20


@dataclass(frozen=True)
class TripMetrics:
    distance_km: float
    duration_minutes: float
    harsh_brakes: int
    harsh_accelerations: int
    speeding_seconds: int
    night_distance_km: float


@dataclass(frozen=True)
class ScoreComponents:
    braking: float
    acceleration: float
    speeding: float
    night: float

    @property
    def total_penalty(self) -> float:
        return self.braking + self.acceleration + self.speeding + self.night

    @property
    def score(self) -> int:
        return max(0, min(100, round(100 - self.total_penalty)))

    def as_dict(self) -> dict:
        return {
            "braking": round(self.braking, 2),
            "acceleration": round(self.acceleration, 2),
            "speeding": round(self.speeding, 2),
            "night": round(self.night, 2),
        }


def trip_components(trip: TripMetrics) -> ScoreComponents:
    per_100km = 100.0 / max(trip.distance_km, 1.0)
    duration_seconds = max(trip.duration_minutes * 60.0, 1.0)
    speeding_percent = min(trip.speeding_seconds / duration_seconds, 1.0) * 100
    night_percent = min(trip.night_distance_km / max(trip.distance_km, 0.1), 1.0) * 100
    return ScoreComponents(
        braking=min(
            MAX_BRAKING_PENALTY, trip.harsh_brakes * per_100km * BRAKING_POINTS_PER_EVENT_PER_100KM
        ),
        acceleration=min(
            MAX_ACCEL_PENALTY,
            trip.harsh_accelerations * per_100km * ACCEL_POINTS_PER_EVENT_PER_100KM,
        ),
        speeding=min(MAX_SPEEDING_PENALTY, speeding_percent * SPEEDING_POINTS_PER_PERCENT),
        night=min(MAX_NIGHT_PENALTY, night_percent * NIGHT_POINTS_PER_PERCENT),
    )


def trip_score(trip: TripMetrics) -> int:
    return trip_components(trip).score


def aggregate(trips: Iterable[TripMetrics]) -> tuple[int, ScoreComponents, float] | None:
    """Distance-weighted score over many trips; None when there isn't enough driving data."""
    trips = list(trips)
    distance = sum(t.distance_km for t in trips)
    if len(trips) < MIN_TRIPS_FOR_SCORE or distance < MIN_DISTANCE_FOR_SCORE_KM:
        return None
    totals = {"braking": 0.0, "acceleration": 0.0, "speeding": 0.0, "night": 0.0}
    for trip in trips:
        components = trip_components(trip)
        weight = trip.distance_km / distance
        totals["braking"] += components.braking * weight
        totals["acceleration"] += components.acceleration * weight
        totals["speeding"] += components.speeding * weight
        totals["night"] += components.night * weight
    combined = ScoreComponents(**totals)
    return combined.score, combined, distance


def dispatch_penalty_minutes(score: int | None) -> float:
    """Extra "virtual minutes" added to a driver's ETA when ranking offers: a driver with a poor
    safety record must be meaningfully closer to win a ride."""
    if score is None or score >= 80:
        return 0.0
    if score >= 60:
        return 1.0
    return 3.0
