"""Product features: several stops, accessible rides, teen accounts, the corporate portal, and
weather and events in the demand forecast."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers.models import DriverProfile, Vehicle
from apps.intelligence import context, demand
from apps.intelligence.models import CityEvent, EventKind, WeatherReading
from apps.payments import services as payments
from apps.riders import corporate, profiles, teens
from apps.riders.models import ProfileKind, RiderProfile
from apps.rides import dispatch
from apps.rides import services as rides
from apps.rides.models import Trip

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db

STOP_A = (13.0368, 80.2676)  # Mylapore
STOP_B = (13.0450, 80.2750)


def midday(now):
    return timezone.make_aware(datetime.combine(timezone.localdate(now), time(12)))


# --- Several stops ---------------------------------------------------------------------------


def test_three_stops_priced_and_stored_in_order(mini, make_driver, now):
    make_driver(now=now)
    direct = rides.estimate_options(rider=None, pickup=T_NAGAR, dropoff=MARINA, at=now)
    two = rides.estimate_options(
        rider=None,
        pickup=T_NAGAR,
        dropoff=MARINA,
        at=now,
        stop=STOP_A,
        extra_stops=[{"lat": STOP_B[0], "lng": STOP_B[1]}],
    )

    def fare(result):
        return next(o for o in result["options"] if o["ride_type"].code == "MINI")["estimate"]

    assert fare(two).route.duration_minutes > fare(direct).route.duration_minutes
    trip = rides.request_trip(
        rider=make_rider(),
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        stop=STOP_A,
        stop_address="Mylapore",
        extra_stops=[{"lat": STOP_B[0], "lng": STOP_B[1], "address": "Santhome"}],
        now=now,
    )
    assert [s["address"] for s in rides.stops_payload(trip)] == ["Mylapore", "Santhome"]
    with pytest.raises(BusinessRuleViolation, match="Up to 3 stops"):
        rides.estimate_options(
            rider=None,
            pickup=T_NAGAR,
            dropoff=MARINA,
            at=now,
            stop=STOP_A,
            extra_stops=[{"lat": 13.04 + i / 200, "lng": 80.26} for i in range(3)],
        )


def test_stops_over_the_api(api, rider, mini, make_driver, now):
    make_driver(now=now)
    body = {
        "ride_type": "MINI",
        "payment_method": "UPI",
        "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
        "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
        "stops": [
            {"lat": STOP_A[0], "lng": STOP_A[1], "address": "A"},
            {"lat": STOP_B[0], "lng": STOP_B[1], "address": "B"},
        ],
    }
    trip = api(rider.user).post("/api/v1/trips/", body, format="json").json()
    assert [s["address"] for s in trip["stops"]] == ["A", "B"]
    assert trip["stop"]["address"] == "A"  # the older single-stop field still works


# --- Accessibility ---------------------------------------------------------------------------


def test_wheelchair_users_only_get_accessible_cars(mini, make_driver, now):
    plain = make_driver(now=now)
    rider = make_rider()
    RiderProfile.objects.filter(pk=rider.pk).update(accessibility=["WHEELCHAIR"])
    rider.refresh_from_db()
    options = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=now)["options"]
    mini_option = next(o for o in options if o["ride_type"].code == "MINI")
    assert (
        mini_option["availability"] == "NONE" and "wheelchair" in mini_option["unavailable_reason"]
    )
    trip = book(rider, mini, now=now)
    assert "WHEELCHAIR" in trip.preferences and pending_offer(trip) is None

    accessible = make_driver(now=now)
    Vehicle.objects.filter(driver=accessible).update(wheelchair_accessible=True)
    dispatch.dispatch_trip(trip, now=now)
    assert pending_offer(trip).driver == accessible
    assert plain != accessible


def test_assistance_prefers_trained_drivers_and_waits_longer(mini, make_driver, now):
    near = make_driver(now=now)
    trained = make_driver(at=(T_NAGAR[0] + 0.012, T_NAGAR[1] + 0.01), now=now)
    DriverProfile.objects.filter(pk=trained.pk).update(assist_trained=True)
    rider = make_rider()
    RiderProfile.objects.filter(pk=rider.pk).update(accessibility=["ASSIST"])
    trip = book(RiderProfile.objects.get(pk=rider.pk), mini, now=now)
    assert pending_offer(trip).driver == trained  # further away, but trained
    trip.waiting_minutes = Decimal(6)
    assert rides._billable_wait(trip) == Decimal(1)  # 5 extra free minutes
    assert near != trained


# --- Teens -----------------------------------------------------------------------------------


def linked_teen(now):
    parent, teen = make_rider(first_name="Anita"), make_rider(first_name="Kiran")
    payments.top_up(parent.user, Decimal(1000), method="UPI", payer_reference="p@upi")
    link = teens.invite(parent, phone=teen.user.phone, monthly_limit=Decimal(2000))
    teens.accept(link, user=teen.user, birth_year=timezone.localdate(now).year - 15, now=now)
    return parent, teen, link


def test_teen_rides_are_paid_by_the_parent_and_shared(mini, make_driver, now):
    now = midday(now)
    parent, teen, link = linked_teen(now)
    rookie = make_driver(now=now)  # a new driver: not allowed to carry teens
    trip = book(teen, mini, now=now)
    assert trip.is_teen and trip.payment_profile_id == link.profile_id
    assert pending_offer(trip) is None
    veteran = make_driver(now=now)
    DriverProfile.objects.filter(pk=veteran.pk).update(rating=Decimal("4.9"), completed_trips=500)
    dispatch.dispatch_trip(trip, now=now)
    assert pending_offer(trip).driver == veteran
    trip = drive_to_completion(trip, now=now)
    titles = list(parent.user.notifications.values_list("title", flat=True))
    assert any("booked a ride" in t for t in titles) and any("arrived" in t for t in titles)
    assert payments.wallet_balance(teen.user) == 0  # the parent paid
    assert rookie != veteran


def test_teen_rules(mini, make_driver, now):
    now = midday(now)
    _, teen, link = linked_teen(now)
    from apps.pricing.models import RideType

    with pytest.raises(BusinessRuleViolation, match="cars and autos"):
        book(teen, RideType.objects.get(code="BIKE"), now=now)
    night = now.replace(hour=23)
    with pytest.raises(BusinessRuleViolation, match="aren't available between 22:00 and 6:00"):
        book(teen, mini, now=night)
    with pytest.raises(BusinessRuleViolation, match="13 to 17"):
        other = make_rider()
        bad = teens.invite(make_rider(), phone=other.user.phone)
        teens.accept(bad, user=other.user, birth_year=timezone.localdate(now).year - 25, now=now)
    assert link.status == "ACTIVE"


# --- Corporate portal ------------------------------------------------------------------------


def company(now):
    owner, employee = make_rider(first_name="Acme"), make_rider(first_name="Ravi")
    profile = profiles.create_profile(
        owner, kind=ProfileKind.BUSINESS, name="Acme Pvt Ltd", gstin="33ABCDE1234F1Z5"
    )
    profile.credit_limit = Decimal(10000)
    profile.save()
    member = profiles.invite(profile, user=owner.user, phone=employee.user.phone)
    profiles.respond(member, user=employee.user, accept=True)
    return owner, employee, profile


def test_travel_policy_and_cost_centres(mini, sedan, make_driver, now):
    now = midday(now)
    owner, employee, profile = company(now)
    corporate.update_policy(
        profile,
        rider=owner,
        allowed_ride_types=["MINI"],
        max_fare_per_trip=Decimal(5000),
        cost_centers=["Sales", "Ops"],
    )
    corporate.update_employee(
        profile,
        rider=owner,
        member_id=profile.members.get(rider=employee).pk,
        default_cost_center="Sales",
    )
    make_driver(now=now)

    def request(ride_type, **extra):
        return rides.request_trip(
            rider=employee,
            ride_type=ride_type,
            pickup=T_NAGAR,
            dropoff=MARINA,
            payment_method="UPI",
            payment_profile=profile,
            trip_purpose="Client visit",
            now=now,
            **extra,
        )

    with pytest.raises(BusinessRuleViolation, match="travel policy allows MINI"):
        request(sedan)
    trip = request(mini)
    assert trip.cost_center == "Sales"  # the employee's default
    trip = drive_to_completion(trip, now=now)
    board = corporate.dashboard(profile, now=now + timedelta(hours=1))
    assert (
        board["this_month"]["rides"] == 1 and board["by_cost_center"][0]["cost_center"] == "Sales"
    )
    pdf, number = corporate.invoice_pdf(profile)
    assert pdf.startswith(b"%PDF") and number.startswith("CORP-")


def test_corporate_api_is_for_managers_only(api, now):
    owner, employee, profile = company(now)
    assert (
        api(owner.user).get(f"/api/v1/rider/business/{profile.pk}/").json()["company"]
        == "Acme Pvt Ltd"
    )
    assert api(employee.user).get(f"/api/v1/rider/business/{profile.pk}/").status_code == 403
    corporate.update_employee(
        profile, rider=owner, member_id=profile.members.get(rider=employee).pk, is_admin=True
    )
    assert api(employee.user).get(f"/api/v1/rider/business/{profile.pk}/").status_code == 200


# --- Weather and events ----------------------------------------------------------------------


def test_rain_and_events_lift_the_forecast(chennai, mini, now):
    hour = demand._hour_start(now) + timedelta(hours=1)
    for weeks in range(1, 5):
        trip = book(make_rider(), mini, now=now)
        Trip.objects.filter(pk=trip.pk).update(
            requested_at=hour - timedelta(weeks=weeks) + timedelta(minutes=5)
        )
    dry = sum(demand.predict(now=now).values())
    WeatherReading.objects.create(
        city=chennai,
        observed_at=now,
        temperature_c=Decimal(25),
        rain_mm=Decimal(6),
        rain_chance_next_3h=90,
        condition="Heavy rain",
        source="simulated",
    )
    assert sum(demand.predict(now=now).values()) == pytest.approx(dry * 1.4)

    CityEvent.objects.create(
        city=chennai,
        name="Big match",
        kind=EventKind.CRICKET,
        venue="Chepauk",
        lat=13.0628,
        lng=80.2793,
        starts_at=hour - timedelta(hours=3),
        ends_at=hour + timedelta(minutes=15),
        expected_attendance=30000,
    )
    with_event = demand.predict(now=now)
    assert sum(with_event.values()) > dry * 1.4 + 100  # the crowd heading home
    info = context.for_rider(13.06, 80.28, now=now)
    assert any("Big match" in m for m in info["messages"]) and any(
        "Heavy rain" in m for m in info["messages"]
    )


def test_weather_falls_back_to_simulation_offline(chennai, now, monkeypatch):
    import requests

    def offline(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "get", offline)
    counts = context.refresh_weather(now=now)
    assert counts["simulated"] >= 1 and counts["open-meteo"] == 0
    reading = context.current_weather(chennai.pk, now=now)
    assert reading.source == "simulated"
    assert context._simulate(chennai, now) == context._simulate(chennai, now)  # deterministic
