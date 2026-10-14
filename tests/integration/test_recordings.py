"""Trip audio recording: encrypted on the device, shared only on report, playback audited."""

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.notifications.models import Notification
from apps.rides import dispatch
from apps.support import recordings
from apps.support.models import SafetyRecording, TicketCategory, TripRecordingKey

from ..conftest import make_rider, make_staff
from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db

AUDIO = b"OggS fake audio bytes for the test" * 20


def assigned_trip(mini, make_driver, now):
    driver = make_driver(now=now)
    rider = make_rider()
    trip = dispatch.accept_offer(pending_offer(book(rider, mini, now=now)), driver=driver, now=now)
    return trip, rider, driver


def encrypt(key: bytes) -> tuple[bytes, bytes]:
    iv = os.urandom(12)
    return AESGCM(key).encrypt(iv, AUDIO, None), iv


def test_record_share_and_play(mini, make_driver, now, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    trip, rider, driver = assigned_trip(mini, make_driver, now)
    key = recordings.start(trip, user=rider.user)
    assert len(key) == 32 and recordings.start(trip, user=rider.user) == key  # same key again
    stored = TripRecordingKey.objects.get(trip=trip, user=rider.user)
    assert key not in bytes(stored.wrapped_key)  # never stored in the clear
    assert Notification.objects.filter(
        user=driver.user, title__startswith="Audio recording"
    ).exists()
    with pytest.raises(ActionNotPermitted):
        recordings.start(trip, user=make_rider().user)

    ciphertext, iv = encrypt(key)
    with pytest.raises(BusinessRuleViolation, match="isn't from this trip"):
        wrong, wrong_iv = encrypt(AESGCM.generate_key(bit_length=256))
        recordings.share(
            trip, user=rider.user, ciphertext=wrong, iv=wrong_iv, mime_type="audio/ogg", duration=5
        )
    recording = recordings.share(
        trip, user=rider.user, ciphertext=ciphertext, iv=iv, mime_type="audio/ogg", duration=42
    )
    assert recording.ticket.category == TicketCategory.SAFETY
    with recording.ciphertext.open("rb") as handle:
        assert AUDIO not in handle.read()  # encrypted at rest

    agent = make_staff(Role.SUPPORT_AGENT)
    audio, mime = recordings.play(recording, actor=agent)
    assert audio == AUDIO and mime == "audio/ogg"
    assert AuditLog.objects.filter(
        message__startswith="Played safety recording", actor=agent
    ).exists()
    with pytest.raises(ActionNotPermitted):
        recordings.play(recording, actor=make_staff(Role.FLEET_EXECUTIVE))


def test_api(api, mini, make_driver, now, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    trip, rider, _driver = assigned_trip(mini, make_driver, now)
    client = api(rider.user)
    key = base64.b64decode(client.post(f"/api/v1/trips/{trip.pk}/recording/start/").json()["key"])
    ciphertext, iv = encrypt(key)
    shared = client.post(
        f"/api/v1/trips/{trip.pk}/recording/share/",
        {
            "file": SimpleUploadedFile("rec.bin", ciphertext),
            "iv": base64.b64encode(iv).decode(),
            "mime_type": "audio/ogg",
            "duration": 30,
        },
        format="multipart",
    )
    assert shared.status_code == 201
    recording = SafetyRecording.objects.get()
    ops = make_staff(Role.OPS_MANAGER)
    listed = api(ops).get(f"/api/v1/safety/recordings/?trip={trip.pk}").json()["results"]
    assert listed[0]["id"] == recording.pk
    played = api(ops).get(f"/api/v1/safety/recordings/{recording.pk}/audio/")
    assert played.status_code == 200 and played.content == AUDIO
    assert (
        api(rider.user).get(f"/api/v1/safety/recordings/{recording.pk}/audio/").status_code == 403
    )
    assert (
        api(make_rider().user).post(f"/api/v1/trips/{trip.pk}/recording/start/").status_code == 404
    )
