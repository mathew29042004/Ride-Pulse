from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.conf import (
    gst_rate,
    platform_commission_percent,
    surge_max_multiplier,
    surge_smoothing,
    surge_window_minutes,
)
from apps.core.exceptions import BusinessRuleViolation
from apps.geo.models import City, Zone
from apps.geo.routing import RouteEstimate, estimate_route_via
from apps.geo.services import zone_for_point

from . import surge
from .fare import FareBreakdown, FareInput, calculate_fare
from .models import FareRule, PromoCode, PromoRedemption, RideType, SurgeOverride, SurgeSnapshot


@dataclass
class FareEstimate:
    ride_type: RideType
    route: RouteEstimate
    fare: FareBreakdown
    surge_multiplier: Decimal
    pickup_zone: Zone | None
    dropoff_zone: Zone | None


def fare_rule(city: City, ride_type: RideType) -> FareRule:
    rule = FareRule.objects.filter(city=city, ride_type=ride_type, is_active=True).first()
    if rule is None:
        raise BusinessRuleViolation(
            f"{ride_type.name} isn't available in {city.name}.", field="ride_type"
        )
    return rule


# --- Surge -------------------------------------------------------------------------------


def current_surge(zone: Zone | None, *, now: datetime | None = None) -> Decimal:
    """A manual override wins; otherwise the latest fresh snapshot; otherwise no surge."""
    if zone is None:
        return Decimal(1)
    from apps.compliance.rules import surge_cap

    return min(_current_surge(zone, now=now), surge_cap(zone.city.state))


def _current_surge(zone: Zone, *, now: datetime | None = None) -> Decimal:
    now = now or timezone.now()
    override = (
        SurgeOverride.objects.filter(zone=zone, starts_at__lte=now, ends_at__gt=now)
        .order_by("-multiplier")
        .values_list("multiplier", flat=True)
        .first()
    )
    if override is not None:
        return override
    fresh_after = now - timedelta(minutes=2 * surge_window_minutes())
    snapshot = (
        SurgeSnapshot.objects.filter(zone=zone, computed_at__gt=fresh_after, computed_at__lte=now)
        .values_list("multiplier", flat=True)
        .first()
    )
    return snapshot if snapshot is not None else Decimal(1)


def recompute_surge(
    *, city: City | None = None, now: datetime | None = None
) -> list[SurgeSnapshot]:
    """Snapshot every zone's multiplier from live demand (recent requests) and supply (online
    drivers currently inside the zone)."""
    from apps.drivers.models import Availability, DriverProfile
    from apps.rides.models import Trip

    now = now or timezone.now()
    since = now - timedelta(minutes=surge_window_minutes())
    cities = [city] if city else list(City.objects.filter(is_active=True))
    cap, alpha = surge_max_multiplier(), surge_smoothing()
    snapshots = []
    for c in cities:
        zones = list(c.zones.all())
        if not zones:
            continue
        demand = dict(
            Trip.objects.filter(city=c, requested_at__gt=since, requested_at__lte=now)
            .values_list("pickup_zone")
            .annotate(n=Count("id"))
        )
        supply: dict[int, int] = {}
        drivers = DriverProfile.objects.filter(
            city=c, availability=Availability.ONLINE, current_lat__isnull=False
        ).values_list("current_lat", "current_lng")
        for lat, lng in drivers:
            zone = zone_for_point(c, lat, lng, zones)
            if zone:
                supply[zone.pk] = supply.get(zone.pk, 0) + 1
        previous = {
            s.zone_id: s.multiplier
            for s in SurgeSnapshot.objects.filter(zone__in=zones)
            .order_by("zone_id", "-computed_at")
            .distinct("zone_id")
        }
        for zone in zones:
            snapshots.append(
                SurgeSnapshot(
                    zone=zone,
                    demand=demand.get(zone.pk, 0),
                    supply=supply.get(zone.pk, 0),
                    multiplier=surge.next_multiplier(
                        previous=previous.get(zone.pk, Decimal(1)),
                        demand=demand.get(zone.pk, 0),
                        supply=supply.get(zone.pk, 0),
                        cap=cap,
                        alpha=alpha,
                    ),
                    computed_at=now,
                )
            )
    return SurgeSnapshot.objects.bulk_create(snapshots)


def surge_board(city: City, *, now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    latest = {
        s.zone_id: s
        for s in SurgeSnapshot.objects.filter(zone__city=city)
        .order_by("zone_id", "-computed_at")
        .distinct("zone_id")
    }
    return [
        {
            "zone": zone,
            "multiplier": current_surge(zone, now=now),
            "demand": latest[zone.pk].demand if zone.pk in latest else 0,
            "supply": latest[zone.pk].supply if zone.pk in latest else 0,
            "computed_at": latest[zone.pk].computed_at if zone.pk in latest else None,
        }
        for zone in city.zones.all()
    ]


# --- Promotions --------------------------------------------------------------------------


def validate_promo(
    code: str, *, rider, city: City, ride_type: RideType, now: datetime | None = None
) -> PromoCode:
    now = now or timezone.now()
    promo = PromoCode.objects.filter(code=code.strip().upper(), is_active=True).first()
    error = None
    if promo is None or not promo.valid_from <= now < promo.valid_until:
        error = "This promo code is invalid or has expired."
    elif promo.city_id and promo.city_id != city.pk:
        error = f"This promo code isn't valid in {city.name}."
    elif promo.ride_types and ride_type.code not in promo.ride_types:
        error = f"This promo code isn't valid for {ride_type.name}."
    elif promo.first_ride_only and rider.completed_trips > 0:
        error = "This promo code is only for your first ride."
    elif promo.max_redemptions is not None and promo.redemptions.count() >= promo.max_redemptions:
        error = "This promo code has been fully redeemed."
    elif promo.redemptions.filter(rider=rider).count() >= promo.max_per_rider:
        error = "You've already used this promo code."
    if error:
        raise BusinessRuleViolation(error, field="promo_code")
    return promo


@transaction.atomic
def redeem_promo(promo: PromoCode, *, rider, trip, amount: Decimal) -> PromoRedemption | None:
    """Records the redemption at trip completion. The promo row is locked so concurrent trips
    can't push it past its redemption limit."""
    promo = PromoCode.objects.select_for_update().get(pk=promo.pk)
    total = promo.redemptions.count()
    by_rider = promo.redemptions.filter(rider=rider).count()
    if (promo.max_redemptions is not None and total >= promo.max_redemptions) or (
        by_rider >= promo.max_per_rider
    ):
        return None
    return PromoRedemption.objects.create(promo=promo, rider=rider, trip=trip, amount=amount)


# --- Estimates ---------------------------------------------------------------------------


def price_trip(
    *,
    city: City,
    ride_type: RideType,
    route: RouteEstimate,
    surge_multiplier: Decimal,
    airport: bool,
    promo: PromoCode | None = None,
    waiting_minutes: Decimal = Decimal(0),
    ride_pass: bool = False,
) -> FareBreakdown:
    from apps.core.conf import ride_pass_terms

    terms = ride_pass_terms() if ride_pass else None
    return calculate_fare(
        FareInput(
            card=fare_rule(city, ride_type).card(),
            distance_km=route.distance_km,
            duration_minutes=route.duration_minutes,
            surge_multiplier=surge_multiplier,
            waiting_minutes=waiting_minutes,
            airport=airport,
            promo=promo.terms() if promo else None,
            gst_rate=gst_rate(),
            commission_percent=platform_commission_percent(),
            pass_percent=terms["percent"] if terms else None,
            pass_max_discount=terms["max_discount"] if terms else Decimal(0),
        )
    )


def estimate_fare(
    *,
    city: City,
    ride_type: RideType,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    at: datetime | None = None,
    promo: PromoCode | None = None,
    stop: tuple[float, float] | None = None,
    ride_pass: bool = False,
    extra_stops=(),
    surge_cap: Decimal | None = None,
) -> FareEstimate:
    at = at or timezone.now()
    zones = list(city.zones.all())
    pickup_zone = zone_for_point(city, *pickup, zones)
    dropoff_zone = zone_for_point(city, *dropoff, zones)
    via = [*([stop] if stop else []), *((s["lat"], s["lng"]) for s in extra_stops)]
    route = estimate_route_via([pickup, *via, dropoff], at)
    multiplier = current_surge(pickup_zone, now=at)
    if surge_cap is not None:  # an A/B test (or policy) capping surge for this rider
        multiplier = min(multiplier, Decimal(str(surge_cap)))
    airport = bool(
        (pickup_zone and pickup_zone.is_airport) or (dropoff_zone and dropoff_zone.is_airport)
    )
    fare = price_trip(
        city=city,
        ride_type=ride_type,
        route=route,
        surge_multiplier=multiplier,
        airport=airport,
        promo=promo,
        ride_pass=ride_pass,
    )
    return FareEstimate(ride_type, route, fare, multiplier, pickup_zone, dropoff_zone)


def active_ride_types(city: City, *, service: str = "RIDE") -> list[RideType]:
    return list(
        RideType.objects.filter(
            is_active=True, service=service, fare_rules__city=city, fare_rules__is_active=True
        )
        .select_related("vehicle_type")
        .order_by("sort_order")
    )


def promo_usage(promo: PromoCode) -> dict:
    return promo.redemptions.aggregate(
        redemptions=Count("id"),
        riders=Count("rider", distinct=True),
        discount_given=Sum("amount", default=Decimal(0)),
    )
