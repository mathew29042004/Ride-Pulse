from datetime import timedelta
from decimal import Decimal

from apps.drivers import services as drivers
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import OfferStatus, Trip

from ..conftest import MARINA, T_NAGAR


def book(rider, ride_type, *, now, pickup=T_NAGAR, dropoff=MARINA, method="UPI", promo=""):
    return rides.request_trip(
        rider=rider,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=dropoff,
        payment_method=method,
        promo_code=promo,
        now=now,
    )


def pending_offer(trip):
    return trip.offers.filter(status=OfferStatus.PENDING).select_related("driver").first()


def drive_to_completion(trip: Trip, *, now, distance=None, payer_reference="") -> Trip:
    """Accept, arrive, start with the PIN and complete, a few minutes apart."""
    offer = pending_offer(trip)
    driver = offer.driver
    trip = dispatch.accept_offer(offer, driver=driver, now=now + timedelta(seconds=10))
    drivers.update_location(
        driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now + timedelta(minutes=4)
    )
    trip = rides.mark_arrived(trip, driver=driver, now=now + timedelta(minutes=4))
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now + timedelta(minutes=5))
    return rides.complete_trip(
        trip,
        driver=driver,
        now=now + timedelta(minutes=5) + timedelta(minutes=float(trip.estimated_duration_min)),
        actual_distance_km=distance if distance is not None else trip.estimated_distance_km,
        payer_reference=payer_reference,
    )


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))
