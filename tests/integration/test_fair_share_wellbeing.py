"""Fair Share Meter and Driver Wellbeing."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.drivers import wellbeing
from apps.drivers.models import Availability, DriverProfile, DriverSession
from apps.notifications.models import Notification
from apps.payments.services import verify_ledger, wallet_balance
from apps.rides import fair_share
from apps.rides import services as rides

from ..conftest import T_NAGAR, make_rider
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


def online_since(driver, start, now):
    """Pretend the driver has been online from ``start`` until ``now`` in one session."""
    DriverSession.objects.filter(driver=driver).delete()
    DriverSession.objects.create(driver=driver, started_at=start)
    DriverProfile.objects.filter(pk=driver.pk).update(availability=Availability.ONLINE)


def test_trip_split_adds_up(rider, mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    split = fair_share.trip_split(trip)
    parts = {p["key"]: p["amount"] for p in split["parts"]}
    assert sum(parts.values()) == split["paid"]
    assert 70 <= split["driver_percent"] <= 90


def test_driver_summary_counts_costs_and_hours(mini, make_driver, now):
    driver = make_driver(now=now)
    online_since(driver, now - timedelta(hours=2), now)
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    later = now + timedelta(hours=1)
    summary = fair_share.driver_summary(driver, now=later)
    assert summary["trips"] == 1
    assert summary["gross_earnings"] == trip.driver_earning
    assert summary["commission_paid"] == trip.platform_commission
    assert summary["running_costs"] > 0
    assert summary["net_earnings"] == summary["gross_earnings"] - summary["running_costs"]
    assert summary["online_hours"] == Decimal("3.0")
    assert summary["net_per_hour"] == (summary["net_earnings"] / 3).quantize(Decimal("0.01"))


def test_breaks_join_short_gaps_and_reset_after_a_real_rest(make_driver, now):
    driver = make_driver(now=now)
    DriverSession.objects.filter(driver=driver).delete()
    DriverSession.objects.create(
        driver=driver, started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=3)
    )
    # A 10-minute pause doesn't count as rest...
    DriverSession.objects.create(driver=driver, started_at=now - timedelta(hours=2, minutes=50))
    assert wellbeing.driving_minutes(driver, now) == 300
    # ...but a 20-minute one does.
    DriverSession.objects.filter(driver=driver, ended_at__isnull=True).update(
        started_at=now - timedelta(hours=2, minutes=40)
    )
    assert wellbeing.driving_minutes(driver, now) == 160


def test_long_stretch_warns_then_forces_a_break(mini, make_driver, now):
    driver = make_driver(now=now)
    online_since(driver, now - timedelta(hours=5, minutes=40), now)
    assert wellbeing.enforce(driver, now) == "warned"
    assert Notification.objects.filter(user=driver.user, title__startswith="Break in").exists()
    assert wellbeing.enforce(driver, now) == ""  # warned once per stretch

    # Past 6 hours: no new offers...
    later = now + timedelta(minutes=25)
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=later)
    assert wellbeing.needs_break(driver, later)
    trip = book(make_rider(), mini, now=later)
    assert not trip.offers.exists()
    rides.cancel_trip(trip, user=trip.rider.user, now=later)

    # ...and the sweep takes them offline for a 20-minute break.
    assert wellbeing.sweep(later)["break"] == 1
    driver.refresh_from_db()
    assert driver.availability == Availability.OFFLINE
    assert driver.break_until == later + timedelta(minutes=20)
    with pytest.raises(BusinessRuleViolation, match="rest break"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=later + timedelta(minutes=5))

    # After the break: back online, with the rest bonus (once a day).
    back = later + timedelta(minutes=21)
    before = wallet_balance(driver.user)
    driver = drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=back)
    assert driver.break_until is None and driver.availability == Availability.ONLINE
    assert wallet_balance(driver.user) == before + Decimal(10)
    assert wellbeing.driving_minutes(driver, back) == 0
    assert verify_ledger()["balanced"]


def test_coming_back_too_soon_is_refused_without_a_recorded_break(make_driver, now):
    driver = make_driver(now=now)
    DriverSession.objects.filter(driver=driver).delete()
    DriverSession.objects.create(
        driver=driver,
        started_at=now - timedelta(hours=6, minutes=10),
        ended_at=now - timedelta(minutes=5),
    )
    DriverProfile.objects.filter(pk=driver.pk).update(availability=Availability.OFFLINE)
    driver.refresh_from_db()
    with pytest.raises(BusinessRuleViolation, match="Rest for 20 minutes"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)


def test_api(api, rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    split = api(rider.user).get(f"/api/v1/trips/{trip.pk}/fair-share/").json()
    assert split["parts"][0]["key"] == "driver"
    assert api(driver.user).get(f"/api/v1/trips/{trip.pk}/fair-share/").status_code == 200
    assert api(make_rider().user).get(f"/api/v1/trips/{trip.pk}/fair-share/").status_code == 404
    summary = api(driver.user).get("/api/v1/driver/fair-share/?days=7").json()
    assert summary["trips"] == 1 and "net_per_hour" in summary
    status = api(driver.user).get("/api/v1/driver/wellbeing/").json()
    assert status["limit_minutes"] == 360 and status["on_break_until"] is None


def test_twelve_hours_in_a_day_means_eight_hours_off(make_driver, now):
    driver = make_driver(now=now)
    DriverSession.objects.filter(driver=driver).delete()
    # Four 3h20m stretches with proper breaks between them: no single stretch is too long,
    # but together they pass 12 hours in 24.
    for k in range(4):
        start = now - timedelta(hours=16) + timedelta(hours=4 * k)
        DriverSession.objects.create(
            driver=driver, started_at=start, ended_at=start + timedelta(hours=3, minutes=20)
        )
    DriverSession.objects.create(driver=driver, started_at=now - timedelta(minutes=30))
    DriverProfile.objects.filter(pk=driver.pk).update(availability=Availability.ONLINE)
    assert wellbeing.daily_minutes(driver, now) >= 720
    assert wellbeing.needs_break(driver, now)
    assert wellbeing.enforce(driver, now) == "break"
    driver.refresh_from_db()
    assert driver.break_until == now + timedelta(hours=8)
    with pytest.raises(BusinessRuleViolation):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now + timedelta(hours=2))
    status = wellbeing.status(driver, now)
    assert status["daily_limit_minutes"] == 720 and status["rest_stops"]  # nearby places to rest


def test_six_working_days_nudges_a_day_off(make_driver, now):
    driver = make_driver(now=now)
    DriverSession.objects.filter(driver=driver).delete()
    for back in range(6):
        start = now - timedelta(days=back, hours=5)
        DriverSession.objects.create(
            driver=driver, started_at=start, ended_at=start + timedelta(hours=4, minutes=30)
        )
    assert wellbeing.days_driven(driver, now) >= 6
    assert wellbeing.nudge_day_off(driver, now)
    assert not wellbeing.nudge_day_off(driver, now)  # once a week
