"""Eco score: how much CO2 a trip saved compared with the rider driving their own petrol car
alone, and eco points the rider can turn into wallet money (100 points = ₹10).

Grams per km come from the vehicle (electric vehicles count the grid's share). It's an estimate,
shown as one: the point is to nudge riders towards bikes, autos and EVs.
"""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.core.conf import eco_terms
from apps.core.exceptions import BusinessRuleViolation
from apps.notifications.models import Level
from apps.notifications.services import notify

ELECTRIC_BONUS_MINUTES = 8.0  # dispatch head start for EVs when the rider prefers electric


def grams_per_km(trip) -> int:
    terms = eco_terms()["per_km"]
    vehicle = trip.vehicle
    if vehicle is not None and vehicle.fuel_type == "EV":
        return terms["EV"]
    code = trip.ride_type.served_by.code
    return terms.get(code, eco_terms()["baseline"])


def saved_grams(trip, distance_km: Decimal) -> int:
    per_km = eco_terms()["baseline"] - grams_per_km(trip)
    return max(0, int(per_km * float(distance_km)))


def award(trip, distance_km: Decimal) -> int:
    """At completion: record the saving and give the rider points. Returns points earned."""
    from apps.riders.models import RiderProfile

    from .models import Trip

    if trip.service == "PARCEL":
        return 0  # the sender isn't travelling
    grams = saved_grams(trip, distance_km)
    points = grams // 100 * eco_terms()["points_per_100g"]
    Trip.objects.filter(pk=trip.pk).update(co2_saved_g=grams)
    trip.co2_saved_g = grams
    RiderProfile.objects.filter(pk=trip.rider_id).update(
        co2_saved_g=F("co2_saved_g") + grams, eco_points=F("eco_points") + points
    )
    return points


def summary(rider, now: datetime | None = None) -> dict:
    from .models import Trip, TripStatus

    now = now or timezone.now()
    terms = eco_terms()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = Trip.objects.filter(
        rider=rider, status=TripStatus.COMPLETED, completed_at__gte=month_start
    ).aggregate(g=Sum("co2_saved_g", default=0))["g"]
    rider.refresh_from_db(fields=["eco_points", "co2_saved_g"])
    return {
        "points": rider.eco_points,
        "co2_saved_kg_total": round(rider.co2_saved_g / 1000, 1),
        "co2_saved_kg_month": round(month / 1000, 1),
        "trees_equivalent": round(rider.co2_saved_g / 21000, 1),  # a tree absorbs ~21 kg a year
        "redeem_points": terms["redeem_points"],
        "redeem_rupees": terms["redeem_rupees"],
        "can_redeem": rider.eco_points >= terms["redeem_points"],
    }


@transaction.atomic
def redeem(rider, now: datetime | None = None) -> dict:
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post
    from apps.riders.models import RiderProfile

    now = now or timezone.now()
    terms = eco_terms()
    rider = RiderProfile.objects.select_for_update().get(pk=rider.pk)
    if rider.eco_points < terms["redeem_points"]:
        raise BusinessRuleViolation(f"You need {terms['redeem_points']} eco points to redeem.")
    batches = rider.eco_points // terms["redeem_points"]
    amount = terms["redeem_rupees"] * batches
    rider.eco_points -= batches * terms["redeem_points"]
    rider.save(update_fields=["eco_points", "updated_at"])
    post(
        TransactionKind.ECO_REWARD,
        [(accounts.PLATFORM_PROMOTIONS, -amount), (ensure_wallet(rider.user), amount)],
        description=f"Eco points: {batches * terms['redeem_points']} redeemed",
        at=now,
    )
    notify(
        rider.user,
        f"₹{amount} for riding green 🌱",
        "Your eco points are now money in your wallet.",
        level=Level.SUCCESS,
        link="/ride/wallet",
    )
    return summary(rider, now)
