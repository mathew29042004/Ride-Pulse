"""Trip audio recording for safety (like Uber's): encrypted on the phone, shared only on report.

1. A rider or driver taps "Record audio" during a trip. The server creates a random per-trip key
   for them (stored wrapped with a key derived from the server secret) and tells the other
   person that a recording is running.
2. The app records with the microphone and encrypts the audio on the device (AES-256-GCM). The
   recording stays on the phone and is deleted there after 7 days.
3. Only if they choose "Send to safety team" is the (still encrypted) file uploaded; it opens or
   joins a safety ticket for the trip.
4. Staff with the safety permission can play it: the server decrypts on demand, and every
   playback is written to the audit trail.
"""

import os
from datetime import timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import SafetyRecording, SupportTicket, TicketCategory, TicketPriority, TripRecordingKey

SHARE_WINDOW = timedelta(days=7)
MAX_BYTES = 8 * 1024 * 1024  # ~1 hour of compressed speech
RECORDABLE = ("DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS")


def _master_key() -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"ridepulse-trip-recordings"
    ).derive(settings.SECRET_KEY.encode())


def _wrap(key: bytes, trip_id: int) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_master_key()).encrypt(nonce, key, str(trip_id).encode())


def _unwrap(wrapped: bytes, trip_id: int) -> bytes:
    wrapped = bytes(wrapped)
    return AESGCM(_master_key()).decrypt(wrapped[:12], wrapped[12:], str(trip_id).encode())


def _participant(trip, user) -> str:
    if trip.rider.user_id == user.pk:
        return "rider"
    if trip.driver_id and trip.driver.user_id == user.pk:
        return "driver"
    raise ActionNotPermitted("Only the rider and driver can record this trip.")


@transaction.atomic
def start(trip, *, user) -> bytes:
    """The raw key for this user's recording on this trip (created on first use)."""
    who = _participant(trip, user)
    if trip.status not in RECORDABLE:
        raise InvalidStateTransition("You can record while a driver is assigned or on the trip.")
    row = TripRecordingKey.objects.filter(trip=trip, user=user).first()
    if row is not None:
        return _unwrap(row.wrapped_key, trip.pk)
    key = AESGCM.generate_key(bit_length=256)
    TripRecordingKey.objects.create(trip=trip, user=user, wrapped_key=_wrap(key, trip.pk))
    other = trip.driver.user if who == "rider" else trip.rider.user
    notify(
        other,
        "Audio recording is on for this trip",
        f"Your {who} is recording audio for safety. It's encrypted and only shared with "
        "Ride Pulse's safety team if they report a problem.",
        level=Level.INFO,
    )
    from apps.rides.services import record_event

    record_event(trip, "RECORDING_STARTED", actor=user, message=f"The {who} started recording")
    return key


@transaction.atomic
def share(
    trip, *, user, ciphertext: bytes, iv: bytes, mime_type: str, duration: int
) -> SafetyRecording:
    """Upload an encrypted recording to the safety team (opens or joins a safety ticket)."""
    from .services import open_ticket

    _participant(trip, user)
    key_row = TripRecordingKey.objects.filter(trip=trip, user=user).first()
    if key_row is None:
        raise BusinessRuleViolation("There's no recording for this trip.")
    ended = trip.completed_at or trip.cancelled_at
    if ended and timezone.now() - ended > SHARE_WINDOW:
        raise BusinessRuleViolation("Recordings can be shared for 7 days after the trip.")
    if not ciphertext or len(ciphertext) > MAX_BYTES or len(iv) != 12:
        raise BusinessRuleViolation("That recording can't be uploaded.", field="file")
    # Refuse anything that wasn't encrypted with this trip's key (and so can't be played).
    try:
        AESGCM(_unwrap(key_row.wrapped_key, trip.pk)).decrypt(iv, ciphertext, None)
    except Exception as exc:  # cryptography raises InvalidTag
        raise BusinessRuleViolation("That recording isn't from this trip.", field="file") from exc
    ticket = (
        SupportTicket.objects.filter(trip=trip, raised_by=user, category=TicketCategory.SAFETY)
        .exclude(status__in=["RESOLVED", "CLOSED"])
        .first()
    )
    if ticket is None:
        ticket = open_ticket(
            user=user,
            category=TicketCategory.SAFETY,
            subject=f"Audio recording from {trip.trip_number}",
            description="A trip audio recording was shared with the safety team.",
            trip=trip,
            priority=TicketPriority.HIGH,
        )
    recording = SafetyRecording(
        trip=trip,
        uploaded_by=user,
        ticket=ticket,
        iv=iv,
        mime_type=mime_type[:60] or "audio/webm",
        duration_seconds=max(0, int(duration)),
        size_bytes=len(ciphertext),
    )
    recording.ciphertext.save(f"trip-{trip.pk}-{user.pk}.bin", ContentFile(ciphertext), save=False)
    recording.save()
    return recording


def play(recording: SafetyRecording, *, actor) -> tuple[bytes, str]:
    """Decrypt for an authorised staff member; every playback is audited."""
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    if not actor.has_capability("safety.manage"):
        raise ActionNotPermitted("Only the safety team can play recordings.")
    key_row = TripRecordingKey.objects.get(trip=recording.trip, user=recording.uploaded_by)
    with recording.ciphertext.open("rb") as handle:
        ciphertext = handle.read()
    audio = AESGCM(_unwrap(key_row.wrapped_key, recording.trip_id)).decrypt(
        bytes(recording.iv), ciphertext, None
    )
    log_event(
        AuditAction.ACTION,
        recording.trip,
        message=f"Played safety recording {recording.pk}",
        actor=actor,
    )
    return audio, recording.mime_type
