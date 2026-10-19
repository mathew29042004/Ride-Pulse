"""Office commute plans: a company (business profile) sets up its office, shift times and work
days; employees enrol with their home pick-up; every evening we book the next day's rides for them.

* Morning: pick-up timed so they arrive by the shift start (drive time + a 15-minute buffer).
* Evening: pick-up at the office when the shift ends.
* Employees skip days (leave, work from home) up to the night before.
* Rides are paid by the company profile with purpose "Office commute", so policy, limits,
  statements and GST e-invoices work as for any business trip.
* Night rides get Night Safe automatically, like any night ride (unless the rider turned it off).
"""

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.core.models import LatitudeField, LongitudeField

BUFFER = timedelta(minutes=15)
PURPOSE = "Office commute"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class CommutePlan(models.Model):
    profile = models.ForeignKey(
        "riders.PaymentProfile", on_delete=models.CASCADE, related_name="commute_plans"
    )
    name = models.CharField(max_length=60)  # e.g. "General shift"
    office_name = models.CharField(max_length=80)
    office_lat = LatitudeField()
    office_lng = LongitudeField()
    ride_type = models.ForeignKey("pricing.RideType", on_delete=models.PROTECT, related_name="+")
    weekdays = ArrayField(models.PositiveSmallIntegerField(), default=list)  # 0 = Monday
    arrive_by = models.TimeField()
    leave_at = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "riders"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.profile_id})"


class CommuteEnrolment(models.Model):
    plan = models.ForeignKey(CommutePlan, on_delete=models.CASCADE, related_name="enrolments")
    rider = models.ForeignKey(
        "riders.RiderProfile", on_delete=models.CASCADE, related_name="commutes"
    )
    home_lat = LatitudeField()
    home_lng = LongitudeField()
    home_address = models.CharField(max_length=255, blank=True)
    morning = models.BooleanField(default=True)
    evening = models.BooleanField(default=True)
    skip_dates = ArrayField(models.DateField(), default=list, blank=True)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "riders"
        constraints = [models.UniqueConstraint(fields=["plan", "rider"], name="commute_enrol_once")]

    def __str__(self) -> str:
        return f"{self.rider_id} on plan {self.plan_id}"


def _manager(profile, rider):
    from .corporate import require_manager

    require_manager(profile, rider)


def create_plan(
    profile, *, rider, name, office_name, office, ride_type, weekdays, arrive_by, leave_at
) -> CommutePlan:
    from apps.geo.services import require_city

    _manager(profile, rider)
    if profile.kind != "BUSINESS":
        raise BusinessRuleViolation("Commute plans are for business profiles.")
    weekdays = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
    if not weekdays:
        raise BusinessRuleViolation("Choose the work days.", field="weekdays")
    if leave_at <= arrive_by:
        raise BusinessRuleViolation("The shift must end after it starts.", field="leave_at")
    require_city(*office)
    return CommutePlan.objects.create(
        profile=profile,
        name=name.strip()[:60] or "Office shift",
        office_name=office_name[:80],
        office_lat=office[0],
        office_lng=office[1],
        ride_type=ride_type,
        weekdays=weekdays,
        arrive_by=arrive_by,
        leave_at=leave_at,
        created_by=rider.user,
    )


def enrol(plan: CommutePlan, *, rider, home, home_address="", morning=True, evening=True):
    from apps.geo.services import require_city

    from .models import MemberStatus

    if not plan.is_active:
        raise BusinessRuleViolation("This commute plan has been stopped.")
    if not plan.profile.members.filter(rider=rider, status=MemberStatus.ACTIVE).exists():
        raise ActionNotPermitted("Join your company's business profile first.")
    if not (morning or evening):
        raise BusinessRuleViolation("Choose the morning ride, the evening ride or both.")
    city = require_city(*home)
    if not city.contains(plan.office_lat, plan.office_lng):
        raise BusinessRuleViolation("Your home is in a different city from the office.")
    enrolment, _ = CommuteEnrolment.objects.update_or_create(
        plan=plan,
        rider=rider,
        defaults={
            "home_lat": home[0],
            "home_lng": home[1],
            "home_address": home_address[:255],
            "morning": morning,
            "evening": evening,
            "is_active": True,
        },
    )
    return enrolment


def skip(
    enrolment: CommuteEnrolment, day: date, *, skip: bool = True, now=None
) -> CommuteEnrolment:
    """Skip (or un-skip) a day. Rides already booked for that day are cancelled."""
    from apps.rides.models import ScheduledRide, ScheduledRideStatus

    today = timezone.localdate(now or timezone.now())
    if day < today:
        raise BusinessRuleViolation("That day has passed.")
    dates = set(enrolment.skip_dates)
    dates.add(day) if skip else dates.discard(day)
    enrolment.skip_dates = sorted(d for d in dates if d >= today)
    enrolment.save(update_fields=["skip_dates"])
    if skip:
        ScheduledRide.objects.filter(
            commute=enrolment, status=ScheduledRideStatus.SCHEDULED, scheduled_for__date=day
        ).update(status=ScheduledRideStatus.CANCELLED)
    return enrolment


def _at(day: date, t: time) -> datetime:
    return timezone.make_aware(datetime.combine(day, t), timezone.get_current_timezone())


def _book(enrolment, *, pickup, dropoff, when, pickup_address, dropoff_address, now):
    from apps.pricing import services as pricing
    from apps.rides.models import ScheduledRide

    plan = enrolment.plan
    if ScheduledRide.objects.filter(commute=enrolment, scheduled_for=when).exists():
        return None
    from apps.geo.services import require_city

    city = require_city(*pickup)
    # The same checks as any booking: service area, trip length, flooded zones.
    from apps.rides.services import _validate_points

    _validate_points(city, pickup, dropoff)
    estimate = pricing.estimate_fare(
        city=city, ride_type=plan.ride_type, pickup=pickup, dropoff=dropoff, at=when
    )
    return ScheduledRide.objects.create(
        rider=enrolment.rider,
        ride_type=plan.ride_type,
        city=city,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        pickup_address=pickup_address[:255],
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        dropoff_address=dropoff_address[:255],
        payment_method="WALLET",
        scheduled_for=when,
        quoted_fare=estimate.fare.total,
        payment_profile=plan.profile,
        commute=enrolment,
    )


def book_day(day: date, *, now=None) -> dict:
    """Book every enrolled employee's rides for ``day`` (run each evening for tomorrow)."""
    from apps.geo.services import require_city
    from apps.pricing import services as pricing

    now = now or timezone.now()
    stats = {"booked": 0, "skipped": 0, "failed": 0}
    enrolments = CommuteEnrolment.objects.filter(
        is_active=True,
        plan__is_active=True,
        plan__profile__is_active=True,
        plan__weekdays__contains=[day.weekday()],
    ).select_related("plan__ride_type", "plan__profile", "rider__user")
    for e in enrolments:
        if day in e.skip_dates:
            stats["skipped"] += 1
            continue
        plan, home, office = (
            e.plan,
            (e.home_lat, e.home_lng),
            (e.plan.office_lat, e.plan.office_lng),
        )
        try:
            if e.morning:
                route = pricing.estimate_fare(
                    city=require_city(*home),
                    ride_type=plan.ride_type,
                    pickup=home,
                    dropoff=office,
                    at=_at(day, plan.arrive_by),
                ).route
                when = (
                    _at(day, plan.arrive_by)
                    - timedelta(minutes=float(route.duration_minutes))
                    - BUFFER
                )
                stats["booked"] += bool(
                    _book(
                        e,
                        pickup=home,
                        dropoff=office,
                        when=when,
                        pickup_address=e.home_address,
                        dropoff_address=plan.office_name,
                        now=now,
                    )
                )
            if e.evening:
                stats["booked"] += bool(
                    _book(
                        e,
                        pickup=office,
                        dropoff=home,
                        when=_at(day, plan.leave_at),
                        pickup_address=plan.office_name,
                        dropoff_address=e.home_address,
                        now=now,
                    )
                )
        except BusinessRuleViolation:
            stats["failed"] += 1
    return stats


def book_tomorrow(*, now=None) -> dict:
    now = now or timezone.now()
    return book_day(timezone.localdate(now) + timedelta(days=1), now=now)


def plan_row(plan: CommutePlan, *, now=None) -> dict:
    from django.db.models import Count, Q, Sum

    from apps.rides.models import ScheduledRide

    now = now or timezone.now()
    month = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rides = ScheduledRide.objects.filter(commute__plan=plan, scheduled_for__gte=month)
    totals = rides.aggregate(
        booked=Count("id"),
        completed=Count("id", filter=Q(trip__status="COMPLETED")),
        failed=Count("id", filter=Q(status="FAILED")),
        cost=Sum("trip__fare_total", filter=Q(trip__status="COMPLETED")),
    )
    return {
        "id": plan.pk,
        "name": plan.name,
        "office_name": plan.office_name,
        "office": [plan.office_lat, plan.office_lng],
        "ride_type": plan.ride_type.code,
        "ride_type_name": plan.ride_type.name,
        "weekdays": plan.weekdays,
        "weekdays_label": ", ".join(WEEKDAYS[d] for d in plan.weekdays),
        "arrive_by": plan.arrive_by.strftime("%H:%M"),
        "leave_at": plan.leave_at.strftime("%H:%M"),
        "is_active": plan.is_active,
        "enrolled": plan.enrolments.filter(is_active=True).count(),
        "this_month": {k: v or 0 for k, v in totals.items()},
    }


def enrolment_row(e: CommuteEnrolment) -> dict:
    from apps.rides.models import ScheduledRide, ScheduledRideStatus

    upcoming = ScheduledRide.objects.filter(
        commute=e, status=ScheduledRideStatus.SCHEDULED
    ).order_by("scheduled_for")[:4]
    return {
        "id": e.pk,
        "plan": plan_row(e.plan),
        "company": e.plan.profile.name,
        "home_address": e.home_address,
        "home": [e.home_lat, e.home_lng],
        "morning": e.morning,
        "evening": e.evening,
        "skip_dates": e.skip_dates,
        "is_active": e.is_active,
        "upcoming": [
            {"id": r.pk, "at": r.scheduled_for, "to": r.dropoff_address} for r in upcoming
        ],
    }


def seed_demo(*, seed: int = 41, log=print) -> dict:
    """Commute plans for the demo companies: a day shift and (for one) a night shift, most
    employees enrolled from homes around the office, and tomorrow's rides booked."""
    import random

    from apps.geo.models import Zone
    from apps.pricing.models import RideType

    from .models import MemberStatus, PaymentProfile

    if CommutePlan.objects.exists():
        return {"commute_plans": 0}
    rng = random.Random(seed)
    mini = RideType.objects.get(code="MINI")
    plans = enrolled = 0
    for profile in PaymentProfile.objects.filter(kind="BUSINESS", is_active=True)[:4]:
        members = list(
            profile.members.filter(status=MemberStatus.ACTIVE).select_related("rider")[:20]
        )
        # The office and homes: neighbourhoods (not the airport) in one city, the one the
        # company's owner rides in most, or any city with enough zones.
        trip = profile.owner.trips.select_related("city").first()
        city_zones = Zone.objects.filter(is_airport=False)
        zones = list(city_zones.filter(city=trip.city)) if trip else []
        if len(zones) < 3:
            from django.db.models import Count

            from apps.geo.models import City

            city = City.objects.annotate(n=Count("zones")).filter(n__gte=4).order_by("?").first()
            zones = list(city_zones.filter(city=city)) if city else []
        if len(zones) < 2 or not members:
            continue
        office = rng.choice(zones)
        shifts = [("General shift", time(9, 30), time(18, 30))]
        if plans == 0:
            shifts.append(("Late shift", time(14, 0), time(23, 0)))
        rng.shuffle(members)
        per_shift = len(members) // len(shifts)
        for n, (name, start, end) in enumerate(shifts):
            plan = CommutePlan.objects.create(
                profile=profile,
                name=name,
                office_name=f"{profile.name}, {office.name}",
                office_lat=office.center_lat,
                office_lng=office.center_lng,
                ride_type=mini,
                weekdays=[0, 1, 2, 3, 4],
                arrive_by=start,
                leave_at=end,
                created_by=profile.owner.user,
            )
            plans += 1
            for member in members[n * per_shift : (n + 1) * per_shift]:
                if rng.random() < 0.2:
                    continue
                home = rng.choice([z for z in zones if z.pk != office.pk])
                CommuteEnrolment.objects.get_or_create(
                    plan=plan,
                    rider=member.rider,
                    defaults={
                        "home_lat": home.center_lat + rng.uniform(-0.005, 0.005),
                        "home_lng": home.center_lng + rng.uniform(-0.005, 0.005),
                        "home_address": f"Home, {home.name}",
                        "evening": rng.random() < 0.85,
                    },
                )
                enrolled += 1
    from apps.notifications import services as notifications

    with notifications.muted():
        booked = book_tomorrow()
    log(f"  commute: {plans} plans, {enrolled} employees, tomorrow {booked}")
    return {"commute_plans": plans, "commuters": enrolled}
