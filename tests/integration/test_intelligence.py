"""Ops intelligence: alerts that create tasks, the morning briefing, demand prediction with
driver nudges, and the fraud review queue."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role, StaffProfile
from apps.drivers.models import OnboardingStatus
from apps.intelligence import alerts, briefing, demand, fraud
from apps.intelligence.models import AlertStatus, DemandNudge, FraudKind, FraudStatus, OpsAlert
from apps.rides.models import Trip, TripFlag, TripStatus
from apps.workspace.models import Priority

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


def staff(user, title, *, city=None, state="", boss=None, department="OPERATIONS"):
    return StaffProfile.objects.create(
        user=user,
        employee_id=f"E{user.pk:05d}",
        title=title,
        department=department,
        city=city,
        state=state,
        reports_to=boss,
        joined_on=date(2025, 1, 1),
    )


def requests(mini, n, *, now, status=None):
    """n trip requests in the last hour (optionally forced into a final status)."""
    trips = []
    for _ in range(n):
        trip = book(make_rider(), mini, now=now)
        trips.append(trip.pk)
    if status:
        Trip.objects.filter(pk__in=trips).update(status=status)
    return trips


def test_cancellation_spike_opens_an_alert_and_a_task(chennai, mini, admin, now):
    regional = make_staff(Role.REGIONAL_MANAGER)
    city_manager = make_staff(Role.OPS_MANAGER)
    boss = staff(regional, "Regional manager", state=chennai.state)
    staff(city_manager, "City manager", city=chennai, boss=boss)

    requests(mini, 10, now=now - timedelta(minutes=20), status=TripStatus.CANCELLED)
    requests(mini, 6, now=now - timedelta(minutes=10))
    result = alerts.check(now=now)
    alert = OpsAlert.objects.get(kind="HIGH_CANCELLATIONS")
    assert result["opened"] == [alert.title] and "62%" in alert.title
    assert alert.owner == city_manager
    assert alert.task.assignee == city_manager and alert.task.assigned_by == regional
    assert alert.task.priority == Priority.URGENT  # 62% is critical

    assert alerts.check(now=now + timedelta(minutes=5))["opened"] == []  # no duplicates
    assert alerts.check(now=now + timedelta(hours=2))["resolved"] == 1  # numbers recovered
    alert.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED


def test_alerts_compare_with_the_citys_normal_level(chennai, mini, now):
    # A city where a third of trips are always cancelled isn't "spiking" at 37%.
    old = requests(mini, 60, now=now - timedelta(days=2))
    Trip.objects.filter(pk__in=old[:25]).update(status=TripStatus.CANCELLED)
    Trip.objects.filter(pk__in=old).update(requested_at=now - timedelta(days=2))
    requests(mini, 6, now=now - timedelta(minutes=5), status=TripStatus.CANCELLED)
    requests(mini, 10, now=now - timedelta(minutes=5))
    assert alerts.check(now=now)["opened"] == []


def test_morning_briefing(mini, make_driver, admin, now):
    make_driver(now=now)
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    yesterday = now - timedelta(days=1)
    Trip.objects.filter(pk=trip.pk).update(requested_at=yesterday, completed_at=yesterday)
    day = timezone.localdate(yesterday)
    made = briefing.generate(day=day, now=now)
    data = made.data
    assert data["trips"]["completed"] == 1 and data["trips"]["completion_rate"] == 100.0
    assert data["headline"].startswith("1 trips completed out of 1 requests")
    assert "₹" in data["headline"]
    assert admin.notifications.filter(title__startswith="Your morning briefing").exists()
    assert briefing.generate(day=day, now=now).pk == made.pk  # rewritten, not duplicated


def test_demand_forecast_and_nudges(chennai, mini, make_driver, now):
    # The same hour every day for two weeks and on the same weekday for four: 6 trips each in
    # T. Nagar (none of them right now).
    hour = demand._hour_start(now) + timedelta(hours=1)
    for back in sorted({*range(1, 15), 21, 28}):
        ids = requests(mini, 6, now=now)
        Trip.objects.filter(pk__in=ids).update(
            requested_at=hour - timedelta(days=back) + timedelta(minutes=10),
            status=TripStatus.CANCELLED,
        )
    zone_id = Trip.objects.values_list("pickup_zone", flat=True).first()
    assert zone_id is not None
    expected = demand.predict(now=now)
    assert expected[zone_id] == pytest.approx(6.0)

    # No drivers near T. Nagar, one 4 km away in Adyar: the zone is short, and they're nudged.
    far = make_driver(at=(13.0012, 80.2565), now=now)
    rows = demand.forecast(now=now)["zones"]
    assert rows[0]["zone_id"] == zone_id and rows[0]["status"] == "SHORT"
    assert demand.nudge_drivers(now=now) == 1
    assert DemandNudge.objects.get().driver == far
    assert demand.nudge_drivers(now=now + timedelta(minutes=10)) == 0  # rate-limited
    assert demand.hot_zones_for(far, now=now)[0]["zone_id"] == zone_id


def test_backtest_scores_the_model_against_simple_guesses(chennai, mini, now):
    hour = demand._hour_start(now)
    for back in range(1, 4):
        ids = requests(mini, 5, now=now)
        Trip.objects.filter(pk__in=ids).update(
            requested_at=hour - timedelta(hours=back, minutes=-5)
        )
    result = demand.backtest(hours=4, now=now)
    assert result["hours"] == 2 and result["trips"] == 10
    assert result["naive"] == 100.0  # steady demand: "same as last hour" is exactly right


def test_fraud_rules_and_review(mini, make_driver, now, admin):
    from apps.drivers import services as drivers

    driver, rider = make_driver(now=now), make_rider()
    trips = []
    for i in range(4):
        start = now + timedelta(hours=i)
        drivers.update_location(driver, lat=13.0448, lng=80.2371, now=start)  # back near pickup
        trips.append(drive_to_completion(book(rider, mini, now=start), now=start).pk)
    Trip.objects.filter(pk__in=trips[:2]).update(flags=[TripFlag.GPS_JUMP])
    assert fraud.scan(now=now + timedelta(hours=5)) == {"opened": 2, "updated": 0}
    kinds = set(fraud.summary()["by_kind"])
    assert kinds == {FraudKind.COLLUSION, FraudKind.GPS_SPOOFING}
    assert fraud.scan(now=now + timedelta(hours=5))["opened"] == 0  # one open case per pattern

    case = fraud.FraudCase.objects.get(kind=FraudKind.GPS_SPOOFING)
    assert case.driver == driver and set(case.trip_ids) == set(trips[:2])
    with pytest.raises(Exception, match="only when confirming"):
        fraud.review(case, user=admin, confirm=False, action="SUSPEND_DRIVER")
    fraud.review(case, user=admin, confirm=True, action="SUSPEND_DRIVER", note="Spoofing app")
    driver.refresh_from_db()
    assert driver.onboarding_status == OnboardingStatus.SUSPENDED

    collusion = fraud.FraudCase.objects.get(kind=FraudKind.COLLUSION)
    fraud.review(collusion, user=admin, confirm=False, note="Family member, regular commute")
    assert fraud.scan(now=now + timedelta(hours=6))["opened"] == 0  # dismissed stays dismissed
    assert collusion.__class__.objects.get(pk=collusion.pk).status == FraudStatus.DISMISSED


def test_api(api, admin, now):
    client = api(admin)
    assert client.get("/api/v1/intel/alerts/").status_code == 200
    assert client.get("/api/v1/intel/fraud/summary/").json()["open"] == 0
    assert "zones" in client.get("/api/v1/intel/demand/").json()
    body = client.get("/api/v1/intel/briefing/").json()
    assert body["briefing"]["trips"]["requests"] == 0
    agent = api(make_staff(Role.SUPPORT_AGENT))
    assert agent.get("/api/v1/intel/fraud/").status_code == 403
