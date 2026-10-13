import itertools
import math
import random
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.drivers.safety import TripMetrics, aggregate, dispatch_penalty_minutes, trip_score
from apps.geo import geohash
from apps.geo.distance import arc, bounding_box, haversine_km, move_along, move_towards
from apps.geo.google import decode_polyline
from apps.geo.routing import average_speed_kmh, heuristic_route
from apps.pricing import surge
from apps.rides import hungarian
from apps.rides.models import TripStatus
from apps.rides.workflow import ALLOWED_TRANSITIONS, can_transition

IST = ZoneInfo("Asia/Kolkata")


# --- Geometry --------------------------------------------------------------------------------


def test_haversine_known_distance():
    # Chennai Central to Chennai Airport is about 14.6 km in a straight line.
    assert haversine_km(13.0827, 80.2757, 12.9941, 80.1709) == pytest.approx(14.9, abs=0.4)


def test_bounding_box_contains_the_circle():
    min_lat, max_lat, min_lng, max_lng = bounding_box(13.0, 80.2, 5)
    assert haversine_km(13.0, 80.2, max_lat, 80.2) == pytest.approx(5, rel=0.01)
    assert haversine_km(13.0, 80.2, 13.0, max_lng) == pytest.approx(5, rel=0.01)
    assert min_lat < 13.0 < max_lat and min_lng < 80.2 < max_lng


def test_move_towards_steps_and_arrives():
    lat, lng, arrived = move_towards(13.0, 80.2, 13.0, 80.3, 1.0)
    assert not arrived and haversine_km(13.0, 80.2, lat, lng) == pytest.approx(1.0, rel=0.02)
    assert move_towards(13.0, 80.2, 13.0, 80.2001, 1.0)[2]


def test_geohash_round_trip_and_known_value():
    assert geohash.encode(57.64911, 10.40744, 11) == "u4pruydqqvj"
    lat, lng, lat_err, lng_err = geohash.decode(geohash.encode(13.0418, 80.2341, 7))
    assert abs(lat - 13.0418) <= lat_err and abs(lng - 80.2341) <= lng_err


def test_nearby_points_share_a_geohash_prefix():
    assert geohash.encode(13.0418, 80.2341, 5) == geohash.encode(13.0425, 80.2350, 5)


def test_rush_hour_is_slower():
    assert average_speed_kmh(datetime(2026, 10, 13, 18, 30, tzinfo=IST)) < average_speed_kmh(
        datetime(2026, 10, 13, 23, 0, tzinfo=IST)
    )
    rush = heuristic_route(
        13.0418, 80.2341, 13.05, 80.2824, datetime(2026, 10, 13, 18, 30, tzinfo=IST)
    )
    night = heuristic_route(
        13.0418, 80.2341, 13.05, 80.2824, datetime(2026, 10, 13, 23, 0, tzinfo=IST)
    )
    assert rush.distance_km == night.distance_km and rush.duration_minutes > night.duration_minutes


def test_decode_google_polyline():
    # Example from Google's polyline algorithm documentation.
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]


# --- Surge -----------------------------------------------------------------------------------


def test_no_surge_when_supply_meets_demand():
    assert surge.raw_multiplier(4, 6, cap=Decimal(3)) == 1
    assert surge.raw_multiplier(0, 0, cap=Decimal(3)) == 1


def test_surge_grows_with_excess_demand_and_is_capped():
    assert surge.raw_multiplier(10, 5, cap=Decimal(3)) == Decimal("1.6")
    assert surge.raw_multiplier(100, 1, cap=Decimal(3)) == Decimal(3)


def test_surge_is_smoothed_and_stepped():
    first = surge.next_multiplier(
        previous=Decimal(1), demand=20, supply=5, cap=Decimal(3), alpha=Decimal("0.5")
    )
    assert first == Decimal("1.9")  # halfway from 1.0 towards 2.8 (ratio 4 → 1 + 3 × 0.6)
    assert surge.to_step(Decimal("1.04"), cap=Decimal(3)) == Decimal("1.0")
    assert surge.to_step(Decimal("9"), cap=Decimal("2.5")) == Decimal("2.5")


# --- Hungarian algorithm ---------------------------------------------------------------------


def brute_force(cost):
    rows, cols = len(cost), len(cost[0])
    best = math.inf
    if rows <= cols:
        for perm in itertools.permutations(range(cols), rows):
            best = min(best, sum(cost[i][j] for i, j in enumerate(perm)))
    else:
        for perm in itertools.permutations(range(rows), cols):
            best = min(best, sum(cost[i][j] for j, i in enumerate(perm)))
    return best


def test_hungarian_known_example():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    pairs = hungarian.solve(cost)
    assert hungarian.total_cost(cost, pairs) == 5


@pytest.mark.parametrize("shape", [(4, 4), (3, 5), (5, 3), (6, 6)])
def test_hungarian_matches_brute_force(shape):
    rng = random.Random(7)
    for _ in range(20):
        cost = [[rng.randint(1, 50) for _ in range(shape[1])] for _ in range(shape[0])]
        pairs = hungarian.solve(cost)
        assert len(pairs) == min(shape)
        assert len({i for i, _ in pairs}) == len(pairs) == len({j for _, j in pairs})
        assert hungarian.total_cost(cost, pairs) == brute_force(cost)


def test_hungarian_skips_forbidden_pairs_but_maximises_matches():
    inf = math.inf
    cost = [[1, inf], [2, inf]]
    assert hungarian.solve(cost) == [(0, 0)]
    # Greedy would give row 0 its cheapest column and strand row 1; optimal matches both.
    cost = [[1, 2], [inf, 3]]
    assert (
        hungarian.solve(cost) == [(0, 0), (1, 1)]
        or hungarian.total_cost(cost, hungarian.solve(cost)) == 4
    )


def test_hungarian_empty():
    assert hungarian.solve([]) == []


# --- Safety score and workflow ---------------------------------------------------------------


def trip(**kw):
    base = {
        "distance_km": 10.0,
        "duration_minutes": 25.0,
        "harsh_brakes": 0,
        "harsh_accelerations": 0,
        "speeding_seconds": 0,
        "night_distance_km": 0.0,
    }
    return TripMetrics(**{**base, **kw})


def test_clean_driving_scores_100_and_events_reduce_it():
    assert trip_score(trip()) == 100
    assert trip_score(trip(harsh_brakes=3, speeding_seconds=300)) < 70


def test_events_are_normalised_by_distance():
    assert trip_score(trip(distance_km=50, harsh_brakes=2)) > trip_score(
        trip(distance_km=5, harsh_brakes=2)
    )


def test_aggregate_needs_enough_driving():
    assert aggregate([trip()] * 3) is None
    score, _, distance = aggregate([trip()] * 5)
    assert score == 100 and distance == 50


def test_poor_safety_costs_dispatch_priority():
    assert (
        dispatch_penalty_minutes(95)
        == 0
        < dispatch_penalty_minutes(70)
        < dispatch_penalty_minutes(40)
    )


def test_trip_state_machine():
    assert can_transition(TripStatus.REQUESTED, TripStatus.DRIVER_ASSIGNED)
    assert can_transition(TripStatus.DRIVER_ASSIGNED, TripStatus.REQUESTED)  # driver cancels
    assert not can_transition(TripStatus.REQUESTED, TripStatus.IN_PROGRESS)
    assert not can_transition(TripStatus.COMPLETED, TripStatus.CANCELLED)
    assert all(
        not ALLOWED_TRANSITIONS[s]
        for s in (TripStatus.COMPLETED, TripStatus.CANCELLED, TripStatus.NO_DRIVER_FOUND)
    )


def test_move_along_follows_the_drawn_route_to_the_end():
    path = arc((13.04, 80.23), (13.05, 80.28))
    lat, lng = path[0]
    travelled, steps, arrived = 0.0, 0, False
    while not arrived and steps < 1000:
        new_lat, new_lng, arrived = move_along(path, lat, lng, 0.05)
        travelled += haversine_km(lat, lng, new_lat, new_lng)
        lat, lng, steps = new_lat, new_lng, steps + 1
        # Every position stays on the curve, never cutting the corner.
        assert min(haversine_km(lat, lng, *p) for p in path) < 0.2
    assert arrived and (lat, lng) == path[-1]
    route_km = sum(haversine_km(*a, *b) for a, b in itertools.pairwise(path))
    assert travelled == pytest.approx(route_km, rel=0.01)
    # A car that has drifted off the line snaps back onto it and carries on.
    off_lat, off_lng, _ = move_along(path, path[10][0] + 0.003, path[10][1], 0.01)
    assert min(haversine_km(off_lat, off_lng, *p) for p in path) < 0.1


def test_polyline_encoding_round_trips():
    from apps.geo.google import encode_polyline

    points = [(13.0418, 80.2341), (13.05, 80.2824), (12.9716, 77.5946), (13.0, 80.0)]
    decoded = decode_polyline(encode_polyline(points))
    assert all(
        abs(a - c) < 1e-5 and abs(b - d) < 1e-5
        for (a, b), (c, d) in zip(points, decoded, strict=True)
    )
    # Google's documented example.
    assert encode_polyline([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == (
        "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    )


def test_route_via_a_stop_adds_both_legs_and_a_stop_allowance():
    from apps.geo.routing import STOP_WAIT_MINUTES, estimate_route_via

    at = datetime(2026, 1, 5, 11, tzinfo=ZoneInfo("Asia/Kolkata"))
    a, stop, b = (13.0418, 80.2341), (13.0604, 80.2496), (13.05, 80.2824)
    direct = estimate_route_via([a, b], at)
    via = estimate_route_via([a, stop, b], at)
    leg1, leg2 = heuristic_route(*a, *stop, at), heuristic_route(*stop, *b, at)
    assert via.distance_km == leg1.distance_km + leg2.distance_km > direct.distance_km
    assert via.duration_minutes == leg1.duration_minutes + leg2.duration_minutes + STOP_WAIT_MINUTES
