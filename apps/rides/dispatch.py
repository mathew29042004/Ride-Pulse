"""Dispatch: matching ride requests to drivers.

Two strategies, chosen with ``RIDE_PULSE["DISPATCH_MODE"]``:

* **SEQUENTIAL** (default): rank nearby drivers and offer the trip to the best one; if they
  decline or the offer times out, offer it to the next.
* **BATCHED**: every sweep, solve one assignment problem over all open requests and free
  drivers in a city with the Hungarian algorithm, minimising total pickup time.

Ranking is ETA-first with small "virtual minute" penalties for a low rating, a low acceptance
rate or a poor safety score, so a slightly further but far better driver can win.

Concurrency: every state change locks the trip row first, then the driver, and the database
enforces one pending offer per trip and per driver, so two dispatch workers can never
double-book a driver.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.conf import (
    dispatch_max_radius_km,
    dispatch_mode,
    dispatch_radius_km,
    offer_timeout_seconds,
)
from apps.core.exceptions import ActionNotPermitted, InvalidStateTransition
from apps.drivers.models import Availability, DriverProfile, Gender
from apps.drivers.safety import dispatch_penalty_minutes
from apps.drivers.services import nearby_available_drivers
from apps.geo.distance import haversine_km
from apps.geo.models import City
from apps.geo.routing import eta_minutes
from apps.realtime import broadcast

from . import hungarian
from .models import OfferStatus, RidePreference, Trip, TripOffer, TripStatus

RADIUS_EXPANSION_AFTER_ATTEMPTS = 2
ACCEPTANCE_WINDOW = 50


@dataclass(frozen=True)
class Candidate:
    driver: DriverProfile
    distance_km: float
    eta_minutes: float
    score: float


# How much a preference moves a driver up the queue, in minutes of pickup time.
FAVOURITE_BONUS_MINUTES = 6.0
WOMAN_DRIVER_BONUS_MINUTES = 30.0  # effectively "women first" among nearby drivers


def rank_score(
    *, eta: float, rating: Decimal, acceptance_rate: Decimal, safety_score: int | None
) -> float:
    """Lower is better. Units are minutes of pickup ETA."""
    rating_penalty = max(0.0, 4.8 - float(rating)) * 2.0
    acceptance_penalty = max(0.0, 90.0 - float(acceptance_rate)) / 20.0
    return eta + rating_penalty + acceptance_penalty + dispatch_penalty_minutes(safety_score)


def _busy_driver_ids() -> list[int]:
    return list(
        TripOffer.objects.filter(status=OfferStatus.PENDING).values_list("driver_id", flat=True)
    )


def candidates_for(
    trip: Trip, *, now: datetime, radius_km: float, limit: int = 10
) -> list[Candidate]:
    # A boost starts a new round: drivers who passed on the old fare get asked again.
    already_offered = trip.offers.filter(round=trip.dispatch_round).values_list(
        "driver_id", flat=True
    )
    drivers = nearby_available_drivers(
        lat=trip.pickup_lat,
        lng=trip.pickup_lng,
        radius_km=radius_km,
        ride_type=trip.ride_type,
        now=now,
        exclude_ids=[*already_offered, *_busy_driver_ids()],
        limit=limit,
    )
    favourites = set(trip.rider.favourite_drivers.values_list("pk", flat=True))
    wants_woman = RidePreference.WOMAN_DRIVER in trip.preferences
    ranked = []
    for driver in drivers:
        eta = eta_minutes(
            driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng, now
        )
        score = rank_score(
            eta=eta,
            rating=driver.rating,
            acceptance_rate=driver.acceptance_rate,
            safety_score=driver.safety_score,
        )
        # Preferences reorder nearby drivers but never leave the rider stranded: if no
        # preferred driver is around, everyone else is still asked.
        if driver.pk in favourites:
            score -= FAVOURITE_BONUS_MINUTES
        if wants_woman and driver.gender == Gender.FEMALE:
            score -= WOMAN_DRIVER_BONUS_MINUTES
        ranked.append(Candidate(driver, driver.distance_km, eta, score))
    return sorted(ranked, key=lambda c: c.score)


def _record(trip: Trip, kind: str, message: str = "", *, data: dict | None = None, at=None) -> None:
    from .services import record_event

    record_event(trip, kind, message=message, data=data, at=at)


def _create_offer(
    trip: Trip, candidate: Candidate, *, now: datetime, mode: str
) -> TripOffer | None:
    try:
        with transaction.atomic():
            offer = TripOffer.objects.create(
                trip=trip,
                driver=candidate.driver,
                offered_at=now,
                expires_at=now + timedelta(seconds=offer_timeout_seconds()),
                distance_km=round(candidate.distance_km, 3),
                eta_minutes=round(candidate.eta_minutes, 2),
                rank_score=round(candidate.score, 3),
                dispatch_mode=mode,
                round=trip.dispatch_round,
            )
    except IntegrityError:
        return None  # the driver just received another offer; try someone else next sweep
    Trip.objects.filter(pk=trip.pk).update(dispatch_attempts=trip.dispatch_attempts + 1)
    trip.dispatch_attempts += 1
    _record(
        trip,
        "OFFER_SENT",
        f"Offered to {candidate.driver.name} "
        f"({candidate.distance_km:.1f} km, ETA {candidate.eta_minutes:.0f} min)",
        data={"driver_id": candidate.driver.pk, "offer_id": offer.pk, "mode": mode},
        at=now,
    )
    broadcast.driver_event(candidate.driver.pk, "offer", offer_payload(offer))
    _push_offer(offer, candidate.driver)
    return offer


def _push_offer(offer: TripOffer, driver: DriverProfile) -> None:
    """Wake the driver's phone even if the app is in the background. Urgent, and it expires
    with the offer, so a late notification is never shown."""
    from apps.notifications import push
    from apps.notifications.models import PushSubscription

    if not (push.enabled() and PushSubscription.objects.filter(user_id=driver.user_id).exists()):
        return
    from apps.notifications.tasks import send_push

    trip = offer.trip
    seconds = max(int((offer.expires_at - timezone.now()).total_seconds()), 1)
    message = {
        "title": f"New {trip.ride_type.name} request · ₹{trip.estimate.driver_earning}",
        "body": f"{offer.distance_km} km away · {trip.pickup_address or 'pickup'} → "
        f"{trip.dropoff_address or 'drop'}",
        "url": "/drive",
        "tag": "offer",
        "ttl": seconds,
        "urgent": True,
    }
    transaction.on_commit(lambda: send_push.delay(driver.user_id, **message))


def offer_payload(offer: TripOffer) -> dict:
    trip = offer.trip
    return {
        "offer_id": offer.pk,
        "trip_id": trip.pk,
        "trip_number": trip.trip_number,
        "ride_type": trip.ride_type.name,
        "pickup": {"lat": trip.pickup_lat, "lng": trip.pickup_lng, "address": trip.pickup_address},
        "dropoff": {
            "lat": trip.dropoff_lat,
            "lng": trip.dropoff_lng,
            "address": trip.dropoff_address,
        },
        "pickup_distance_km": offer.distance_km,
        "pickup_eta_min": offer.eta_minutes,
        "trip_distance_km": trip.estimated_distance_km,
        "estimated_earning": trip.estimate.driver_earning,
        "boost": trip.boost_amount,
        "tip": trip.tip_pledged,
        "preferences": trip.preferences,
        "surge": trip.surge_multiplier,
        "payment_method": trip.payment_method,
        "expires_at": offer.expires_at,
    }


@transaction.atomic
def dispatch_trip(trip: Trip, *, now: datetime | None = None) -> TripOffer | None:
    """Offer an open request to the best available driver (sequential mode)."""
    now = now or timezone.now()
    trip = Trip.objects.select_for_update(of=("self",)).select_related("ride_type").get(pk=trip.pk)
    if (
        trip.status != TripStatus.REQUESTED
        or trip.offers.filter(status=OfferStatus.PENDING).exists()
    ):
        return None
    if now >= trip.dispatch_deadline:
        from .services import expire_request

        expire_request(trip, now=now)
        return None
    radius = float(
        dispatch_max_radius_km()
        if trip.dispatch_attempts >= RADIUS_EXPANSION_AFTER_ATTEMPTS or trip.boost_amount > 0
        else dispatch_radius_km()
    )
    for candidate in candidates_for(trip, now=now, radius_km=radius):
        offer = _create_offer(trip, candidate, now=now, mode="SEQUENTIAL")
        if offer:
            return offer
    return None


@transaction.atomic
def accept_offer(offer: TripOffer, *, driver: DriverProfile, now: datetime | None = None) -> Trip:
    from .services import assign_driver

    now = now or timezone.now()
    trip = Trip.objects.select_for_update().get(pk=offer.trip_id)
    offer = TripOffer.objects.select_for_update().get(pk=offer.pk)
    if offer.driver_id != driver.pk:
        raise ActionNotPermitted("This offer was sent to another driver.")
    if offer.status != OfferStatus.PENDING:
        raise InvalidStateTransition(
            f"This offer is no longer available ({offer.get_status_display().lower()})."
        )
    if now >= offer.expires_at:
        _close_offer(offer, OfferStatus.EXPIRED, now=now)
        raise InvalidStateTransition("This offer has expired.")
    if trip.status != TripStatus.REQUESTED:
        _close_offer(offer, OfferStatus.WITHDRAWN, now=now)
        raise InvalidStateTransition("The rider cancelled this trip.")
    _close_offer(offer, OfferStatus.ACCEPTED, now=now)
    trip = assign_driver(trip, driver=driver, eta_minutes=offer.eta_minutes, now=now)
    recompute_acceptance_rate(driver)
    return trip


@transaction.atomic
def decline_offer(offer: TripOffer, *, driver: DriverProfile, now: datetime | None = None) -> None:
    now = now or timezone.now()
    offer = TripOffer.objects.select_for_update().get(pk=offer.pk)
    if offer.driver_id != driver.pk:
        raise ActionNotPermitted("This offer was sent to another driver.")
    if offer.status != OfferStatus.PENDING:
        raise InvalidStateTransition("This offer is no longer pending.")
    _close_offer(offer, OfferStatus.DECLINED, now=now)
    _record(
        offer.trip,
        "OFFER_DECLINED",
        f"{driver.name} declined",
        data={"driver_id": driver.pk},
        at=now,
    )
    recompute_acceptance_rate(driver)
    redispatch(offer.trip, now=now)


def _close_offer(offer: TripOffer, status: str, *, now: datetime) -> None:
    offer.status = status
    offer.responded_at = now
    offer.save(update_fields=["status", "responded_at"])
    if status in (OfferStatus.EXPIRED, OfferStatus.WITHDRAWN):
        broadcast.driver_event(
            offer.driver_id, "offer_closed", {"offer_id": offer.pk, "status": status}
        )


def redispatch(trip: Trip, *, now: datetime) -> None:
    if dispatch_mode() == "SEQUENTIAL":
        dispatch_trip(trip, now=now)
    # In batched mode the next sweep picks the trip up together with everything else.


def withdraw_trip_offers(trip: Trip, *, now: datetime) -> int:
    offers = list(trip.offers.filter(status=OfferStatus.PENDING))
    for offer in offers:
        _close_offer(offer, OfferStatus.WITHDRAWN, now=now)
    return len(offers)


def withdraw_driver_offers(driver: DriverProfile, *, now: datetime | None = None) -> int:
    """The driver went offline: pass their pending offers to someone else."""
    now = now or timezone.now()
    offers = list(
        TripOffer.objects.filter(driver=driver, status=OfferStatus.PENDING).select_related("trip")
    )
    for offer in offers:
        _close_offer(offer, OfferStatus.WITHDRAWN, now=now)
        redispatch(offer.trip, now=now)
    return len(offers)


def recompute_acceptance_rate(driver: DriverProfile) -> Decimal:
    recent = list(
        TripOffer.objects.filter(
            driver=driver,
            status__in=[OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED],
        )
        .order_by("-offered_at")
        .values_list("status", flat=True)[:ACCEPTANCE_WINDOW]
    )
    rate = (
        Decimal(100) * sum(1 for s in recent if s == OfferStatus.ACCEPTED) / len(recent)
        if recent
        else Decimal(100)
    ).quantize(Decimal("0.01"))
    DriverProfile.objects.filter(pk=driver.pk).update(acceptance_rate=rate)
    driver.acceptance_rate = rate
    return rate


# --- Batched dispatch --------------------------------------------------------------------


@transaction.atomic
def batch_dispatch(
    city: City, *, now: datetime | None = None, max_requests: int = 60
) -> list[TripOffer]:
    """Assign all open requests in a city at once with minimum total pickup ETA."""
    now = now or timezone.now()
    radius = float(dispatch_max_radius_km())
    trips = list(
        Trip.objects.select_for_update(skip_locked=True, of=("self",))
        .filter(city=city, status=TripStatus.REQUESTED, dispatch_deadline__gt=now)
        .exclude(offers__status=OfferStatus.PENDING)
        .select_related("ride_type")
        .order_by("requested_at")[:max_requests]
    )
    if not trips:
        return []
    busy = set(_busy_driver_ids())
    drivers = [
        d
        for d in DriverProfile.objects.filter(
            city=city, availability=Availability.ONLINE, current_lat__isnull=False
        ).prefetch_related("vehicles")
        if d.pk not in busy and d.active_vehicle is not None
    ]
    if not drivers:
        return []
    offered = {
        (t, d)
        for t, d in TripOffer.objects.filter(trip__in=trips).values_list("trip_id", "driver_id")
    }
    cost: list[list[float]] = []
    pickup_etas: dict[tuple[int, int], tuple[float, float]] = {}
    for trip in trips:
        row = []
        for driver in drivers:
            if (
                driver.active_vehicle.ride_type_id != trip.ride_type_id
                or (trip.pk, driver.pk) in offered
            ):
                row.append(math.inf)
                continue
            distance = haversine_km(
                driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng
            )
            if distance > radius:
                row.append(math.inf)
                continue
            eta = eta_minutes(
                driver.current_lat, driver.current_lng, trip.pickup_lat, trip.pickup_lng, now
            )
            pickup_etas[(trip.pk, driver.pk)] = (distance, eta)
            row.append(
                rank_score(
                    eta=eta,
                    rating=driver.rating,
                    acceptance_rate=driver.acceptance_rate,
                    safety_score=driver.safety_score,
                )
            )
        cost.append(row)

    offers = []
    for i, j in hungarian.solve(cost):
        trip, driver = trips[i], drivers[j]
        distance, eta = pickup_etas[(trip.pk, driver.pk)]
        offer = _create_offer(
            trip, Candidate(driver, distance, eta, cost[i][j]), now=now, mode="BATCHED"
        )
        if offer:
            offers.append(offer)
    return offers


# --- Sweeper -----------------------------------------------------------------------------


def expire_offers(*, now: datetime | None = None) -> int:
    now = now or timezone.now()
    expired = 0
    for offer in TripOffer.objects.filter(
        status=OfferStatus.PENDING, expires_at__lte=now
    ).select_related("trip", "driver"):
        with transaction.atomic():
            locked = TripOffer.objects.select_for_update().get(pk=offer.pk)
            if locked.status != OfferStatus.PENDING:
                continue
            _close_offer(locked, OfferStatus.EXPIRED, now=now)
            _record(offer.trip, "OFFER_EXPIRED", f"{offer.driver.name} didn't respond", at=now)
            recompute_acceptance_rate(offer.driver)
            redispatch(offer.trip, now=now)
            expired += 1
    return expired


def sweep(*, now: datetime | None = None) -> dict:
    """One dispatcher tick: time out stale offers and requests, then match open requests."""
    from .services import expire_request

    now = now or timezone.now()
    result = {"offers_expired": expire_offers(now=now), "requests_expired": 0, "offers_sent": 0}
    for trip in Trip.objects.filter(status=TripStatus.REQUESTED, dispatch_deadline__lte=now):
        with transaction.atomic():
            locked = Trip.objects.select_for_update().get(pk=trip.pk)
            if locked.status == TripStatus.REQUESTED:
                expire_request(locked, now=now)
                result["requests_expired"] += 1

    if dispatch_mode() == "BATCHED":
        cities = City.objects.filter(trips__status=TripStatus.REQUESTED).distinct()
        for city in cities:
            result["offers_sent"] += len(batch_dispatch(city, now=now))
    else:
        waiting = (
            Trip.objects.filter(status=TripStatus.REQUESTED, dispatch_deadline__gt=now)
            .annotate(pending=Count("offers", filter=Q(offers__status=OfferStatus.PENDING)))
            .filter(pending=0)
            .order_by("requested_at")
        )
        for trip in waiting:
            if dispatch_trip(trip, now=now):
                result["offers_sent"] += 1
    return result
