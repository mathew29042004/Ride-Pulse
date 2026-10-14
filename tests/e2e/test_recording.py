"""Trip audio recording end to end: the browser encrypts with Web Crypto, the server decrypts."""

import pytest

pytest.importorskip("playwright", reason="install requirements/dev.txt for browser tests")
from playwright.sync_api import expect

from apps.accounts.models import Role
from apps.pricing.models import RideType
from apps.riders.services import register_rider
from apps.rides import dispatch
from apps.rides import services as rides
from apps.support import recordings
from apps.support.models import SafetyRecording

from ..conftest import MARINA, make_staff
from .test_new_flows import PASSWORD, sign_in

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]


def test_record_on_the_phone_and_share_with_safety(page, live_server, make_driver, now):
    rider = register_rider(
        email="e2e.recorder@test.dev", password=PASSWORD, first_name="Asha", phone="9800000199"
    )
    driver = make_driver(now=now)
    trip = rides.request_trip(
        rider=rider,
        ride_type=RideType.objects.get(code="MINI"),
        pickup=(driver.current_lat, driver.current_lng),
        dropoff=MARINA,
        payment_method="UPI",
    )
    trip = dispatch.accept_offer(trip.offers.get(), driver=driver)
    sign_in(page, live_server, rider.user.email)
    page.context.grant_permissions(["microphone"])
    page.goto(f"{live_server.url}/ride/trips/{trip.pk}/")

    page.get_by_role("button", name="Record audio for safety").click()
    expect(page.get_by_text("Recording…")).to_be_visible()
    page.wait_for_timeout(2500)
    page.get_by_role("button", name="Recording…").click()  # stop
    page.get_by_role("button", name="Send to safety team").click()
    expect(page.get_by_text("Sent to the safety team")).to_be_visible()

    recording = SafetyRecording.objects.get(trip=trip)
    audio, mime = recordings.play(recording, actor=make_staff(Role.SUPPORT_AGENT))
    assert len(audio) > 500 and mime.startswith("audio/")  # Web Crypto ↔ server AES-GCM agree
