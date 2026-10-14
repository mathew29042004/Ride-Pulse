"""Bid your fare (like inDrive) and Sure Ride.

**Bid your fare.** The rider offers their own price, between 85% and 150% of the upfront fare.
Drivers see the offer next to the usual fare and either accept or counter with +₹10/20/30. A
counter goes to the rider, who has two minutes to take it (if that driver is still free); the
search carries on meanwhile. The agreed difference from the usual fare is applied like a boost:
all of it is the driver's, outside commission and GST.

**Sure Ride.** For a small fee the rider gets "a driver at your pickup within N minutes, or ₹30
back" (N = the nearest driver's ETA plus a buffer). If the driver isn't there by then, or nobody
is found, the refund lands in the rider's wallet automatically.
"""

import math
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.core.conf import fare_offer_rules, sure_ride_terms
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.notifications.models import Level
from apps.notifications.services import notify
from apps.realtime import broadcast

from .models import CancelledBy, OfferStatus, Trip, TripOffer, TripStatus

SURE_RIDE_CODE = "SURE_RIDE"


def _rupees(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("1"))


def offer_bounds(upfront: Decimal) -> tuple[Decimal, Decimal]:
    rules = fare_offer_rules()
    return _rupees(upfront * rules["min_ratio"]), _rupees(upfront * rules["max_ratio"])


def check_offer(upfront: Decimal, offer: Decimal) -> Decimal:
    """The adjustment (offer − upfront) if the offer is in range."""
    low, high = offer_bounds(upfront)
    if not low <= offer <= high:
        raise BusinessRuleViolation(
            f"Offer between ₹{low} and ₹{high} for this ride.", field="fare_offer"
        )
    return (Decimal(offer) - upfront).quantize(Decimal("0.01"))


# --- Counter-offers -----------------------------------------------------------------------


@transaction.atomic
def counter(offer: TripOffer, *, driver, extra: Decimal, now: datetime | None = None) -> TripOffer:
    """The driver would take the trip for the rider's offer + ``extra``."""
    from . import dispatch

    now = now or timezone.now()
    extra = Decimal(extra)
    offer = TripOffer.objects.select_for_update().select_related("trip").get(pk=offer.pk)
    trip = offer.trip
    if offer.driver_id != driver.pk:
        raise ActionNotPermitted("This offer was sent to another driver.")
    if offer.status != OfferStatus.PENDING:
        raise InvalidStateTransition("This offer is no longer pending.")
    if trip.fare_offer is None:
        raise BusinessRuleViolation("Counter-offers are only for rides where the rider bids.")
    if extra not in fare_offer_rules()["counter_steps"]:
        raise BusinessRuleViolation("Counter with +₹10, +₹20 or +₹30.", field="extra")
    offer.status = OfferStatus.COUNTERED
    offer.responded_at = now
    offer.counter_amount = trip.estimated_fare + extra
    offer.save(update_fields=["status", "responded_at", "counter_amount"])
    dispatch._record(
        trip,
        "COUNTER_OFFER",
        f"{driver.name} countered with ₹{offer.counter_amount}",
        data={"driver_id": driver.pk, "amount": str(offer.counter_amount)},
        at=now,
    )
    notify(
        trip.rider.user,
        f"{driver.user.first_name or 'A driver'} can come for ₹{offer.counter_amount}",
        "Tap to accept the counter-offer, or keep waiting for your price.",
        level=Level.INFO,
        link=f"/ride/trips/{trip.pk}/",
    )
    broadcast.trip_event(trip.pk, "counter_offer", {"offer_id": offer.pk})
    dispatch.redispatch(trip, now=now)  # keep looking at the rider's price meanwhile
    return offer


def open_counters(trip: Trip, now: datetime | None = None):
    now = now or timezone.now()
    valid = timedelta(seconds=fare_offer_rules()["counter_valid_seconds"])
    return (
        trip.offers.filter(status=OfferStatus.COUNTERED, responded_at__gte=now - valid)
        .select_related("driver__user")
        .order_by("counter_amount")
    )


@transaction.atomic
def take_counter(offer: TripOffer, *, user, now: datetime | None = None) -> Trip:
    """The rider accepts a driver's counter-offer: the fare becomes that amount."""
    from apps.drivers.models import Availability
    from apps.pricing.fare import with_offer_adjustment

    from . import dispatch
    from .services import assign_driver

    now = now or timezone.now()
    trip = Trip.objects.select_for_update().get(pk=offer.trip_id)
    offer = TripOffer.objects.select_for_update().select_related("driver").get(pk=offer.pk)
    if trip.rider.user_id != user.pk:
        raise ActionNotPermitted("Only the rider can accept a counter-offer.")
    if trip.status != TripStatus.REQUESTED:
        raise InvalidStateTransition("This request already has a driver or was closed.")
    valid = timedelta(seconds=fare_offer_rules()["counter_valid_seconds"])
    if offer.status != OfferStatus.COUNTERED or now - offer.responded_at > valid:
        raise InvalidStateTransition("This counter-offer has expired.")
    if offer.driver.availability != Availability.ONLINE:
        raise InvalidStateTransition("That driver isn't available any more.")
    adjustment = trip.offer_adjustment + (offer.counter_amount - trip.estimated_fare)
    fare = with_offer_adjustment(trip.estimate, adjustment)
    trip.offer_adjustment = adjustment
    trip.fare_offer = offer.counter_amount
    trip.estimated_fare = fare.total
    trip.fare_estimate = fare.to_dict()
    trip.save(
        update_fields=[
            "offer_adjustment",
            "fare_offer",
            "estimated_fare",
            "fare_estimate",
            "updated_at",
        ]
    )
    dispatch.withdraw_trip_offers(trip, now=now)
    offer.status = OfferStatus.ACCEPTED
    offer.save(update_fields=["status"])
    trip = assign_driver(trip, driver=offer.driver, eta_minutes=offer.eta_minutes, now=now)
    notify(
        offer.driver.user,
        f"Rider accepted your ₹{offer.counter_amount}",
        "Head to the pickup.",
        level=Level.SUCCESS,
        link="/drive",
    )
    return trip


# --- Sure Ride ------------------------------------------------------------------------------


def sure_ride_minutes(eta_minutes: float) -> int:
    terms = sure_ride_terms()
    return max(terms["min_minutes"], math.ceil(eta_minutes) + terms["buffer_minutes"])


def sure_ride_quote(eta_minutes: float | None) -> dict | None:
    if eta_minutes is None:
        return None
    terms = sure_ride_terms()
    return {
        "minutes": sure_ride_minutes(eta_minutes),
        "fee": terms["fee"],
        "refund": terms["refund"],
    }


def promise_broken(trip: Trip, now: datetime) -> bool:
    if not trip.sure_ride_deadline or trip.sure_ride_refunded_at:
        return False
    if trip.arrived_at:
        return trip.arrived_at > trip.sure_ride_deadline
    if trip.status == TripStatus.CANCELLED and trip.cancelled_by == CancelledBy.RIDER:
        # The rider changed their mind before the promise ran out: nothing owed.
        return trip.cancelled_at > trip.sure_ride_deadline
    if trip.status in (TripStatus.NO_DRIVER_FOUND, TripStatus.CANCELLED):
        return True  # nobody came, or the driver/ops cancelled on the rider
    return now > trip.sure_ride_deadline


@transaction.atomic
def refund_if_late(trip: Trip, *, now: datetime | None = None) -> bool:
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post

    now = now or timezone.now()
    trip = (
        Trip.objects.select_for_update(of=("self",)).select_related("rider__user").get(pk=trip.pk)
    )
    if not promise_broken(trip, now):
        return False
    refund = sure_ride_terms()["refund"]
    post(
        TransactionKind.REFUND,
        [(accounts.PLATFORM_PROMOTIONS, -refund), (ensure_wallet(trip.rider.user), refund)],
        trip=trip,
        description=f"Sure Ride: driver not there within {trip.sure_ride_minutes} min",
        at=now,
    )
    trip.sure_ride_refunded_at = now
    trip.save(update_fields=["sure_ride_refunded_at", "updated_at"])
    notify(
        trip.rider.user,
        f"₹{refund} back: Sure Ride",
        f"Your driver wasn't there within {trip.sure_ride_minutes} minutes, so ₹{refund} is "
        "in your wallet. Sorry for the wait!",
        level=Level.SUCCESS,
        link="/ride/wallet",
    )
    return True


def sweep(now: datetime | None = None) -> int:
    """Pay out every broken Sure Ride promise (called with the dispatch sweep)."""
    now = now or timezone.now()
    due = (
        Trip.objects.filter(
            sure_ride_deadline__isnull=False,
            sure_ride_refunded_at__isnull=True,
            arrived_at__isnull=True,
        )
        .filter(
            Q(sure_ride_deadline__lt=now)
            | Q(status=TripStatus.NO_DRIVER_FOUND)
            | Q(status=TripStatus.CANCELLED, cancelled_by__in=[CancelledBy.DRIVER, CancelledBy.OPS])
        )
        .exclude(cancelled_by=CancelledBy.RIDER, cancelled_at__lte=F("sure_ride_deadline"))
    )
    return sum(refund_if_late(trip, now=now) for trip in due)
