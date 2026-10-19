"""Booking counters at railway stations and bus stands, for people without a smartphone.

* A counter sits at a station landmark. Staff with ``counter.operate`` book a ride for a walk-up
  passenger: destination, ride type, the passenger's name (and phone, if they have one).
* The fare is fixed upfront. The passenger pays cash at the counter; the cash goes into the
  counter's account on the ledger and the trip is paid from it, so the driver is paid as usual.
* The passenger gets a printed slip (booking number, Ride PIN, car and driver once assigned) and,
  if they gave a phone number, the same by SMS.
* End of day: cash taken per counter and per staff member, to match against the cash drawer.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.core.money import ZERO


class Counter(models.Model):
    landmark = models.OneToOneField(
        "geo.Landmark", on_delete=models.PROTECT, related_name="counter"
    )
    # A rider account for the counter: its wallet holds the counter's cash and pays its trips.
    account = models.OneToOneField(
        "riders.RiderProfile", on_delete=models.PROTECT, related_name="counter"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "rides"

    def __str__(self) -> str:
        return f"Counter at {self.landmark}"


class CounterBooking(models.Model):
    counter = models.ForeignKey(Counter, on_delete=models.PROTECT, related_name="bookings")
    trip = models.OneToOneField(
        "rides.Trip", on_delete=models.PROTECT, related_name="counter_booking"
    )
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    passenger_name = models.CharField(max_length=80)
    passenger_phone = models.CharField(max_length=15, blank=True)
    cash = models.DecimalField(max_digits=9, decimal_places=2)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "rides"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.trip_id} at {self.counter_id}"


def open_counter(landmark) -> Counter:
    from apps.riders.services import register_rider

    if landmark.category != "TRANSIT":
        raise BusinessRuleViolation("Counters are at railway stations and bus stands.")
    existing = Counter.objects.filter(landmark=landmark).first()
    if existing:
        return existing
    account = register_rider(
        email=f"counter-{landmark.pk}@counters.ridepulse.in",
        password=None,
        first_name="Counter",
        last_name=landmark.name[:100],
    )
    return Counter.objects.create(landmark=landmark, account=account)


@transaction.atomic
def book(
    counter: Counter,
    *,
    staff,
    ride_type,
    dropoff: tuple[float, float],
    dropoff_address: str,
    passenger_name: str,
    passenger_phone: str = "",
    now=None,
) -> CounterBooking:
    from apps.payments import accounts
    from apps.payments.models import TransactionKind
    from apps.payments.services import ensure_wallet, post
    from apps.pricing import services as pricing

    from . import services as rides

    now = now or timezone.now()
    if not staff.has_capability("counter.operate"):
        raise ActionNotPermitted("Only counter staff can book here.")
    if not counter.is_active:
        raise BusinessRuleViolation("This counter is closed.")
    name = passenger_name.strip()
    if len(name) < 2:
        raise BusinessRuleViolation(
            "Enter the passenger's name for the slip.", field="passenger_name"
        )
    phone = "".join(ch for ch in passenger_phone if ch.isdigit())[-10:]
    if passenger_phone and len(phone) != 10:
        raise BusinessRuleViolation(
            "Enter a 10-digit mobile number, or leave it empty.", field="passenger_phone"
        )
    lm = counter.landmark
    pickup = (lm.lat, lm.lng)
    estimate = pricing.estimate_fare(
        city=lm.city, ride_type=ride_type, pickup=pickup, dropoff=dropoff, at=now
    )
    cash = estimate.fare.total
    wallet = ensure_wallet(counter.account.user)
    post(
        TransactionKind.COUNTER_CASH,
        [(wallet, cash), (accounts.COUNTER_CASH, -cash)],
        description=f"Cash for {name} at {lm.name}",
        at=now,
        actor=staff,
    )
    trip = rides.request_trip(
        rider=counter.account,
        ride_type=ride_type,
        pickup=pickup,
        dropoff=dropoff,
        payment_method="WALLET",
        pickup_address=f"{lm.name} (booking counter)",
        dropoff_address=dropoff_address,
        now=now,
    )
    booking = CounterBooking.objects.create(
        counter=counter,
        trip=trip,
        booked_by=staff,
        passenger_name=name,
        passenger_phone=phone,
        cash=cash,
        created_at=now,
    )
    if phone:
        from apps.accounts.sms import send_text

        send_text(
            phone,
            f"Ride Pulse: {ride_type.name} to {dropoff_address or 'your destination'} booked, "
            f"paid Rs {cash}. Your Ride PIN is {trip.otp}. Wait at the {lm.name} counter.",
        )
    return booking


def slip(b: CounterBooking) -> dict:
    trip = b.trip
    return {
        "id": b.pk,
        "trip_id": trip.pk,
        "trip_number": trip.trip_number,
        "passenger": b.passenger_name,
        "phone": b.passenger_phone[-4:] if b.passenger_phone else "",
        "pin": trip.otp,
        "from": trip.pickup_address,
        "to": trip.dropoff_address,
        "ride_type": trip.ride_type.name,
        "cash": b.cash,
        "status": trip.status,
        "status_label": trip.get_status_display(),
        "driver": trip.driver.name if trip.driver_id else None,
        "vehicle": trip.vehicle.registration_display if trip.vehicle_id else None,
        "booked_by": b.booked_by.get_full_name(),
        "created_at": b.created_at,
    }


def day_summary(counter: Counter, *, day=None) -> dict:
    day = day or timezone.localdate()
    rows = CounterBooking.objects.filter(counter=counter, created_at__date=day)
    by_staff = rows.values("booked_by__first_name", "booked_by__last_name").annotate(
        n=Count("id"), cash=Sum("cash")
    )
    return {
        "day": day,
        "bookings": rows.count(),
        "cash": rows.aggregate(t=Sum("cash"))["t"] or ZERO,
        "by_staff": [
            {
                "name": f"{r['booked_by__first_name']} {r['booked_by__last_name']}".strip(),
                "bookings": r["n"],
                "cash": r["cash"] or Decimal(0),
            }
            for r in by_staff
        ],
    }


def seed_demo(*, log=print) -> dict:
    """A counter at every railway station and bus stand in the network."""
    from apps.geo.models import Landmark

    if Counter.objects.exists():
        return {"counters": 0}
    made = [
        open_counter(lm) for lm in Landmark.objects.filter(category="TRANSIT", city__is_active=True)
    ]
    log(f"  booking counters: {len(made)}")
    return {"counters": len(made)}
