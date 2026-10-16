"""Guardian mode: when something goes wrong, the rider's live location goes to their trusted
contacts (opt-in), follows the phone or the car, reminds if it goes quiet, and ends on "I'm safe"."""

from datetime import timedelta
from unittest import mock

import pytest

from apps.riders.models import ShareMode, TrustedContact
from apps.rides import guardian, safety
from apps.rides.models import EmergencyShare, RideCheck, RideCheckKind, ShareTrigger
from apps.support.services import raise_sos
from apps.trust.models import ConsentPurpose
from apps.trust.privacy import has_consent

from ..conftest import T_NAGAR, make_rider
from .test_safety import start_ride

pytestmark = pytest.mark.django_db


@pytest.fixture
def texts():
    with mock.patch("apps.accounts.sms.send_text") as send:
        yield send


def guarded_rider(api=None):
    rider = make_rider()
    TrustedContact.objects.create(
        rider=rider, name="Amma", phone="9876500001", share_mode=ShareMode.NEVER
    )
    TrustedContact.objects.create(
        rider=rider, name="Priya", phone="9876500002", share_mode=ShareMode.NEVER
    )
    return rider


def test_off_by_default_and_turning_it_on_needs_a_contact(api, texts):
    lonely = make_rider()
    client = api(lonely.user)
    assert client.get("/api/v1/safety/guardian/status/").json()["guardian_mode"] is False
    response = client.post("/api/v1/safety/guardian/settings/", {"guardian_mode": True})
    assert response.status_code == 422
    rider = guarded_rider()
    client = api(rider.user)
    status = client.post(
        "/api/v1/safety/guardian/settings/", {"guardian_mode": True, "fake_call_name": "Appa"}
    ).json()
    assert status["guardian_mode"] and status["fake_call_name"] == "Appa"
    assert has_consent(rider.user, ConsentPurpose.CONTACT_SHARING)  # switching on is consent


def test_sos_shares_live_location_with_every_contact(mini, make_driver, now, texts):
    rider = guarded_rider()
    rider.guardian_mode = True
    rider.save()
    driver = make_driver(now=now)
    trip = start_ride(rider, mini, driver, now)
    raise_sos(trip=trip, user=rider.user, lat=13.05, lng=80.24, note="Help", now=now)
    share = EmergencyShare.objects.get(rider=rider)
    assert share.triggers == [ShareTrigger.SOS] and share.contacts_alerted == 2
    assert (share.last_lat, share.last_source) == (13.05, "PHONE")
    message = texts.call_args_list[-1].args[1]
    assert "maps.google.com/?q=13.05000,80.24000" in message and f"/safe/{share.token}" in message
    # A second trigger joins the same alert; no second round of texts.
    sent = texts.call_count
    guardian.start(rider, ShareTrigger.SHAKE, trip=trip, now=now)
    assert texts.call_count == sent and EmergencyShare.objects.get(rider=rider).triggers == [
        "SOS",
        "SHAKE",
    ]


def test_not_shared_unless_the_rider_opted_in(mini, make_driver, now, texts):
    rider = guarded_rider()  # Guardian mode off
    trip = start_ride(rider, mini, make_driver(now=now), now)
    raise_sos(trip=trip, user=rider.user, note="Help", now=now)
    assert not EmergencyShare.objects.exists()


def test_ride_check_shares_early_and_ok_ends_it(mini, make_driver, now, texts):
    rider = guarded_rider()
    rider.guardian_mode = True
    rider.save()
    trip = start_ride(rider, mini, make_driver(now=now), now)
    check = safety._raise(trip, RideCheckKind.LONG_STOP, now)
    share = EmergencyShare.objects.get(rider=rider)
    assert share.is_active and share.last_source == "CAR"  # the car's location
    safety.answer(check, user=rider.user, ok=True, now=now + timedelta(minutes=1))
    share.refresh_from_db()
    assert share.ended_by == "RIDER"
    assert "safe now" in texts.call_args_list[-1].args[1]
    assert RideCheck.objects.get(pk=check.pk).status == "OK"


def test_phone_location_wins_and_quiet_phone_reminds_contacts(mini, make_driver, now, texts):
    rider = guarded_rider()
    rider.guardian_mode = True
    rider.save()
    trip = start_ride(rider, mini, make_driver(now=now), now)
    share = guardian.start(rider, ShareTrigger.MANUAL, trip=trip, lat=13.0, lng=80.2, now=now)
    guardian.record(share, lat=13.2, lng=80.3, source="CAR", now=now + timedelta(seconds=30))
    share.refresh_from_db()
    assert share.last_lat == 13.0  # a fresh phone fix beats the car
    guardian.phone_location(rider, lat=13.01, lng=80.21, now=now + timedelta(minutes=1))
    share.refresh_from_db()
    assert share.last_lat == 13.01
    # Nothing newer arrives from the phone or the car: remind contacts, up to 3 times.
    sent = texts.call_count
    for minutes in (8, 12, 19, 30, 41, 52):
        guardian.sweep(now=now + timedelta(minutes=minutes))
    share.refresh_from_db()
    assert share.reminders_sent == 3 and texts.call_count == sent + 6  # 2 contacts × 3
    guardian.sweep(now=now + timedelta(hours=13))
    share.refresh_from_db()
    assert share.ended_by == "EXPIRED"


def test_public_page_and_im_safe(api, mini, make_driver, now, texts):
    rider = guarded_rider()
    client = api(rider.user)
    client.post("/api/v1/safety/guardian/settings/", {"guardian_mode": True})
    status = client.post(
        "/api/v1/safety/guardian/share/",
        {"trigger": "MANUAL", "lat": T_NAGAR[0], "lng": T_NAGAR[1]},
    ).json()
    token = status["share"]["link"].rsplit("/", 1)[1]
    anonymous = api(None)
    page = anonymous.get(f"/api/v1/safe/{token}/").json()
    assert page["active"] and page["location"]["lat"] == pytest.approx(T_NAGAR[0])
    client.post("/api/v1/safety/guardian/location/", {"lat": 13.06, "lng": 80.25})
    assert anonymous.get(f"/api/v1/safe/{token}/").json()["location"]["lat"] == 13.06
    assert client.post("/api/v1/safety/guardian/safe/").json()["share"] is None
    page = anonymous.get(f"/api/v1/safe/{token}/").json()
    assert not page["active"] and page["location"] is None and page["phone"] is None
    assert anonymous.get("/api/v1/safe/not-a-token/").status_code == 404


def test_shake_on_a_trip_raises_sos(api, mini, make_driver, now, texts):
    from apps.support.models import SafetyIncident

    rider = guarded_rider()
    rider.guardian_mode = True
    rider.save()
    start_ride(rider, mini, make_driver(now=now), now)
    client = api(rider.user)
    client.post("/api/v1/safety/guardian/share/", {"trigger": "SHAKE", "lat": 13.05, "lng": 80.24})
    assert SafetyIncident.objects.filter(trip__rider=rider).exists()
    assert set(EmergencyShare.objects.get(rider=rider).triggers) == {"SOS", "SHAKE"}
