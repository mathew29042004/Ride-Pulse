"""Office commute plans: a company sets up a shift, employees enrol, tomorrow's rides are booked
(morning timed to arrive by shift start, evening at shift end), skipped days aren't booked, and
the rides go out as business trips paid by the company."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.payments import services as payments
from apps.pricing.models import RideType
from apps.riders import commute, profiles
from apps.rides import services as rides
from apps.rides.models import ScheduledRide, ScheduledRideStatus

from ..conftest import MARINA, T_NAGAR, make_rider

pytestmark = pytest.mark.django_db

OFFICE = MARINA
HOME = T_NAGAR


@pytest.fixture
def company():
    owner = make_rider(first_name="Owner")
    profile = profiles.create_profile(owner, kind="BUSINESS", name="Acme Pvt Ltd")
    profile.credit_limit = Decimal(20_000)
    profile.save()
    employee = make_rider(first_name="Anita")
    invitation = profiles.invite(profile, user=owner.user, phone=employee.user.phone)
    profiles.respond(invitation, user=employee.user, accept=True)
    return profile, owner, employee


def make_plan(profile, owner, **kw):
    return commute.create_plan(
        profile,
        rider=owner,
        name="General shift",
        office_name="Acme, Marina",
        office=OFFICE,
        ride_type=RideType.objects.get(code="MINI"),
        weekdays=kw.get("weekdays", list(range(7))),
        arrive_by=time(9, 30),
        leave_at=time(18, 30),
    )


def test_only_managers_create_plans_and_only_members_enrol(company):
    profile, owner, employee = company
    with pytest.raises(ActionNotPermitted):
        make_plan(profile, employee)
    plan = make_plan(profile, owner)
    with pytest.raises(ActionNotPermitted, match="business profile"):
        commute.enrol(plan, rider=make_rider(first_name="Stranger"), home=HOME)
    with pytest.raises(BusinessRuleViolation):
        commute.enrol(plan, rider=employee, home=HOME, morning=False, evening=False)


def test_tomorrow_is_booked_skips_respected_and_rides_are_business_trips(company, make_driver, now):
    profile, owner, employee = company
    plan = make_plan(profile, owner)
    e = commute.enrol(plan, rider=employee, home=HOME, home_address="Home, T. Nagar")
    tomorrow = timezone.localdate(now) + timedelta(days=1)
    stats = commute.book_tomorrow(now=now)
    assert stats["booked"] == 2
    assert commute.book_tomorrow(now=now)["booked"] == 0  # not twice
    morning, evening = ScheduledRide.objects.filter(commute=e).order_by("scheduled_for")
    assert timezone.localtime(morning.scheduled_for).time() < time(9, 15)  # drive + 15 min buffer
    assert timezone.localtime(evening.scheduled_for).time() == time(18, 30)
    assert morning.payment_profile == profile

    commute.skip(e, tomorrow, now=now)
    assert not ScheduledRide.objects.filter(
        commute=e, status=ScheduledRideStatus.SCHEDULED
    ).exists()
    day_after = tomorrow + timedelta(days=1)
    commute.skip(e, day_after, now=now)
    assert commute.book_day(day_after, now=now)["skipped"] == 1

    # Un-skip tomorrow, rebook, and send the morning ride out: paid by the company.
    commute.skip(e, tomorrow, skip=False, now=now)
    ScheduledRide.objects.filter(commute=e).delete()
    commute.book_day(tomorrow, now=now)
    morning = ScheduledRide.objects.filter(commute=e).order_by("scheduled_for").first()
    make_driver(now=morning.scheduled_for)
    rides.dispatch_scheduled_rides(now=morning.scheduled_for - timedelta(minutes=5))
    morning.refresh_from_db()
    assert morning.trip.payment_profile == profile
    assert morning.trip.trip_purpose == "Office commute"
    assert payments.wallet_balance(employee.user) == 0


def test_api(api, company):
    profile, owner, employee = company
    admin = api(owner.user)
    made = admin.post(
        f"/api/v1/rider/business/{profile.pk}/commute/plan/",
        {
            "name": "Night shift",
            "office_name": "Acme",
            "office_lat": OFFICE[0],
            "office_lng": OFFICE[1],
            "ride_type": "MINI",
            "weekdays": [0, 1, 2, 3, 4],
            "arrive_by": "21:00",
            "leave_at": "23:45",
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    me = api(employee.user)
    offered = me.get("/api/v1/rider/commute/").json()
    assert offered["plans"][0]["id"] == made.json()["id"]
    enrolled = me.post(
        "/api/v1/rider/commute/enrol/",
        {"plan": made.json()["id"], "home_lat": HOME[0], "home_lng": HOME[1]},
        format="json",
    )
    assert enrolled.status_code == 200
    board = admin.get(f"/api/v1/rider/business/{profile.pk}/commute/").json()
    assert board["plans"][0]["enrolled"] == 1
    stopped = admin.post(f"/api/v1/rider/business/{profile.pk}/commute/{made.json()['id']}/stop/")
    assert not stopped.json()["is_active"]


def test_a_home_too_far_from_the_office_is_not_booked(company, now):
    profile, owner, employee = company
    plan = make_plan(profile, owner)
    # Saved directly (the enrol screen refuses this): home 600 km away in another city.
    commute.CommuteEnrolment.objects.create(
        plan=plan, rider=employee, home_lat=15.8497, home_lng=74.4977, home_address="Belagavi"
    )
    stats = commute.book_tomorrow(now=now)
    assert stats["booked"] == 0 and stats["failed"] == 1


def test_pooled_plan_pairs_neighbours(company, now):
    from apps.pricing.models import RideType

    profile, owner, employee = company
    neighbour = make_rider(first_name="Bala")
    invitation = profiles.invite(profile, user=owner.user, phone=neighbour.user.phone)
    profiles.respond(invitation, user=neighbour.user, accept=True)
    plan = make_plan(profile, owner)
    plan.pool = True
    plan.save()
    commute.enrol(plan, rider=employee, home=HOME)
    commute.enrol(plan, rider=neighbour, home=(HOME[0] + 0.004, HOME[1]))  # ~450 m away
    commute.book_tomorrow(now=now)
    mornings = sorted(
        ScheduledRide.objects.filter(
            commute__plan=plan, dropoff_address="Acme, Marina"
        ).values_list("scheduled_for", "ride_type__code")
    )
    assert [code for _, code in mornings] == ["SHARE", "SHARE"]
    assert mornings[1][0] - mornings[0][0] == timedelta(minutes=1)
    assert RideType.objects.filter(code="SHARE").exists()
