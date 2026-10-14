"""Safety+: Ride Check, Night Safe mode, trusted contacts and "I'm home safe"."""

from datetime import timedelta
from unittest import mock

import pytest

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.drivers import services as drivers
from apps.geo.distance import offset
from apps.notifications.models import Notification
from apps.riders.models import ShareMode, TrustedContact
from apps.rides import dispatch, safety
from apps.rides import services as rides
from apps.rides.models import RideCheck, RideCheckKind, RideCheckStatus, TripFlag
from apps.support.models import SafetyIncident

from ..conftest import T_NAGAR, make_rider
from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db

ALWAYS_NIGHT = [0, 24]


def start_ride(rider, ride_type, driver, now, **kwargs):
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    trip = book(rider, ride_type, now=now, **kwargs)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    return rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)


@pytest.fixture
def night(settings):
    settings.RIDE_PULSE = {**settings.RIDE_PULSE, "NIGHT_SAFE_HOURS": ALWAYS_NIGHT}


@pytest.fixture
def day(settings, now):
    hour = (now.hour + 12) % 24  # a one-hour window far from now
    settings.RIDE_PULSE = {**settings.RIDE_PULSE, "NIGHT_SAFE_HOURS": [hour, hour + 1]}


@pytest.fixture
def texts():
    with mock.patch("apps.accounts.sms.send_text") as send:
        yield send


def test_night_safe_mode_is_decided_at_start(
    day, mini, make_driver, now, django_capture_on_commit_callbacks
):
    driver = make_driver(now=now)
    with django_capture_on_commit_callbacks(execute=True):
        trip = start_ride(make_rider(), mini, driver, now)
    assert not trip.night_safe  # daytime
    drivers.update_location(driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now)
    rides.complete_trip(trip, driver=driver, now=now + timedelta(minutes=20))

    # A "woman driver" ride is Night Safe at any hour, unless the rider turned it off.
    rider = make_rider()
    driver.gender = "F"
    driver.save()
    trip = start_ride(rider, mini, driver, now, preferences=["WOMAN_DRIVER"])
    assert trip.night_safe
    assert safety.is_night(now) is False


def test_trusted_contacts_get_the_live_link(
    night, mini, make_driver, now, texts, django_capture_on_commit_callbacks
):
    rider = make_rider()
    TrustedContact.objects.create(
        rider=rider, name="Amma", phone="9876511111", share_mode=ShareMode.NIGHT
    )
    TrustedContact.objects.create(
        rider=rider, name="Office", phone="9876522222", share_mode=ShareMode.NEVER
    )
    with django_capture_on_commit_callbacks(execute=True):
        trip = start_ride(rider, mini, make_driver(now=now), now)
    trip.refresh_from_db()
    assert trip.night_safe and trip.contacts_notified_at and trip.share_token
    texts.assert_called_once()
    phone, message = texts.call_args.args
    assert phone == "9876511111" and f"/track/{trip.share_token}" in message
    assert safety.share_with_contacts(trip.pk) == 0  # only once


def test_long_stop_check_escalates_when_nobody_answers(night, mini, make_driver, now, texts):
    rider = make_rider()
    TrustedContact.objects.create(
        rider=rider, name="Amma", phone="9876511111", share_mode=ShareMode.NEVER
    )
    driver = make_driver(now=now)
    trip = start_ride(rider, mini, driver, now)
    lat, lng = offset(trip.pickup_lat, trip.pickup_lng, 0.5, 0.5)
    for minute in range(5):  # parked for 4+ minutes, on the route
        drivers.update_location(driver, lat=lat, lng=lng, now=now + timedelta(minutes=minute))
    later = now + timedelta(minutes=4, seconds=10)
    result = safety.run_ride_checks(later)
    check = RideCheck.objects.get(trip=trip)
    assert result["raised"] == 1 and check.kind == RideCheckKind.LONG_STOP
    assert Notification.objects.filter(user=rider.user, title="Is everything OK?").exists()
    assert Notification.objects.filter(user=driver.user, title="Are you OK?").exists()
    assert safety.run_ride_checks(later)["raised"] == 0  # once per kind

    # Three minutes without an answer (Night Safe): the safety team and every contact hear.
    drivers.update_location(driver, lat=lat, lng=lng, now=later + timedelta(minutes=3))
    assert safety.run_ride_checks(later + timedelta(minutes=3, seconds=5))["escalated"] == 1
    check.refresh_from_db()
    trip.refresh_from_db()
    assert check.status == RideCheckStatus.ESCALATED and check.incident
    assert TripFlag.RIDE_CHECK in trip.flags and TripFlag.SOS in trip.flags
    assert SafetyIncident.objects.filter(trip=trip).count() == 1
    assert texts.call_args.args[0] == "9876511111"  # even a "never share" contact
    assert "safety alert" in texts.call_args.args[1]


def test_answers_ok_help_and_driver(night, mini, make_driver, now, texts):
    rider, driver = make_rider(), make_driver(now=now)
    trip = start_ride(rider, mini, driver, now)
    # Far off the route (3 km sideways) at night: an off-route check.
    lat, lng = offset(trip.pickup_lat, trip.pickup_lng, 3, -3)
    drivers.update_location(driver, lat=lat, lng=lng, now=now + timedelta(minutes=1))
    safety.run_ride_checks(now + timedelta(minutes=1))
    check = RideCheck.objects.get(trip=trip, kind=RideCheckKind.OFF_ROUTE)

    with pytest.raises(ActionNotPermitted):
        safety.answer(check, user=make_rider().user, ok=True)
    assert safety.answer(check, user=rider.user, ok=True).status == RideCheckStatus.OK
    # Answering OK closes it for good: no escalation later.
    assert safety.run_ride_checks(now + timedelta(minutes=10))["escalated"] == 0

    # Running very late, and the rider asks for help: escalated straight away.
    late = now + timedelta(minutes=float(trip.estimated_duration_min) * 1.3 + 11)
    drivers.update_location(driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=late)
    safety.run_ride_checks(late)
    late_check = RideCheck.objects.get(trip=trip, kind=RideCheckKind.RUNNING_LATE)
    helped = safety.answer(late_check, user=rider.user, ok=False)
    assert helped.status == RideCheckStatus.HELP and helped.incident

    # The driver can say they're fine (or ask for help) on their own checks.
    assert safety.answer(late_check, user=driver.user, ok=True).driver_ok is True


def test_night_safe_ride_ends_at_the_drop_unless_the_rider_confirms(night, mini, make_driver, now):
    rider, driver = make_rider(), make_driver(now=now)
    trip = start_ride(rider, mini, driver, now)
    halfway = offset(trip.dropoff_lat, trip.dropoff_lng, 2, 0)
    drivers.update_location(driver, lat=halfway[0], lng=halfway[1], now=now)
    with pytest.raises(BusinessRuleViolation):
        rides.complete_trip(trip, driver=driver, now=now + timedelta(minutes=15))
    with pytest.raises(ActionNotPermitted):
        safety.confirm_early_drop(trip, user=driver.user)
    safety.confirm_early_drop(trip, user=rider.user)
    assert Notification.objects.filter(
        user=driver.user, title="Rider confirmed the drop here"
    ).exists()
    trip = rides.complete_trip(trip, driver=driver, now=now + timedelta(minutes=15))
    assert trip.status == "COMPLETED"


def test_home_safe_check_in(
    night, mini, make_driver, now, texts, django_capture_on_commit_callbacks
):
    rider, driver = make_rider(), make_driver(now=now)
    TrustedContact.objects.create(rider=rider, name="Amma", phone="9876511111")
    with django_capture_on_commit_callbacks(execute=True):
        trip = start_ride(rider, mini, driver, now)
    drivers.update_location(driver, lat=trip.dropoff_lat, lng=trip.dropoff_lng, now=now)
    trip = rides.complete_trip(trip, driver=driver, now=now + timedelta(minutes=20))
    trip = safety.home_safe(trip, user=rider.user, now=now + timedelta(minutes=30))
    assert trip.home_safe_at and "reached safely" in texts.call_args.args[1]
    assert safety.home_safe(trip, user=rider.user).home_safe_at == trip.home_safe_at  # once


def test_simulated_riders_answer_their_own_checks(night, mini, make_driver, now):
    rider, driver = make_rider(), make_driver(now=now)
    rider.user.email = "bot1@example.com"
    rider.user.save()
    trip = start_ride(rider, mini, driver, now)
    RideCheck.objects.create(trip=trip, kind=RideCheckKind.RUNNING_LATE, created_at=now)
    assert safety.answer_for_bots(now) == 1
    assert safety.run_ride_checks(now + timedelta(minutes=10))["escalated"] == 0


def test_safety_api(api, night, mini, make_driver, now, ops):
    rider, driver = make_rider(), make_driver(now=now)
    client = api(rider.user)
    url = "/api/v1/rider/contacts/"
    assert client.post(url, {"name": "Amma", "phone": "12345"}).status_code == 400
    made = client.post(url, {"name": "Amma", "phone": "+91 98765 11111", "share_mode": "ALWAYS"})
    assert made.status_code == 201, made.json()
    assert made.json()["phone"] == "9876511111"
    assert client.post(url, {"name": "Again", "phone": "9876511111"}).status_code == 409
    client.post(url, {"name": "B", "phone": "9876522222"})
    client.post(url, {"name": "C", "phone": "9876533333"})
    assert client.post(url, {"name": "D", "phone": "9876544444"}).status_code == 422  # max 3
    assert len(client.get(url).json()) == 3
    assert api(make_rider().user).get(url).json() == []  # only your own

    assert (
        client.patch("/api/v1/rider/me/", {"night_safety": False}, format="json").json()[
            "night_safety"
        ]
        is False
    )
    client.patch("/api/v1/rider/me/", {"night_safety": True}, format="json")

    trip = start_ride(rider, mini, driver, now)
    check = RideCheck.objects.create(trip=trip, kind=RideCheckKind.LONG_STOP, created_at=now)
    seen = client.get(f"/api/v1/trips/{trip.pk}/").json()
    assert seen["night_safe"] is True and seen["open_ride_check"]["id"] == check.pk
    assert (
        api(driver.user).get(f"/api/v1/trips/{trip.pk}/").json()["open_ride_check"]["kind"]
        == "LONG_STOP"
    )
    answered = client.post(f"/api/v1/ride-checks/{check.pk}/answer/", {"ok": True}).json()
    assert answered["status"] == "OK"
    assert client.get(f"/api/v1/trips/{trip.pk}/").json()["open_ride_check"] is None
    assert (
        api(make_rider().user)
        .post(f"/api/v1/ride-checks/{check.pk}/answer/", {"ok": True})
        .status_code
        == 404
    )
    assert api(ops).get("/api/v1/ride-checks/").json()["results"][0]["id"] == check.pk

    assert (
        client.post(f"/api/v1/trips/{trip.pk}/early-drop/").json()["early_drop_confirmed"] is True
    )
