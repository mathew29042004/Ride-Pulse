"""Personal data rights, built along the lines of India's Digital Personal Data Protection Act,
2023 (DPDP).

* **Consent:** each optional purpose (offers, personalisation, analytics, sharing trips with
  trusted contacts) is opt-in and can be withdrawn as easily as it was given. Every change is
  recorded with the notice version the person saw (``ConsentRecord`` is append-only).
* **Access:** "Download my data" builds a JSON archive of everything held about the person,
  available for 7 days.
* **Erasure:** "Delete my account" waits 7 days (it can be cancelled), then erases personal
  details: name, email, phone, saved places, trusted contacts, chats, push subscriptions,
  notifications, recording keys and documents. Financial records (trips, fares, ledger,
  invoices) are kept, without a name attached, because tax law requires them (8 years). It is
  refused while a trip is active or money is owed.
* **Requests** get a reference number and a response deadline (``PRIVACY_RESPONSE_DAYS``) and
  appear in the ops privacy queue, handled by the grievance team.
* **Retention:** a daily job removes data that's past its purpose (see ``RETENTION``).
"""

import io
import json
import zipfile
from datetime import datetime, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, ConflictError, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import ConsentPurpose, ConsentRecord, DataRequest, RequestKind, RequestStatus

NOTICE_VERSION = "2026-10"
COOLING_OFF = timedelta(days=7)
EXPORT_TTL = timedelta(days=7)
# What's kept, for how long, and why (shown in the privacy centre; enforced by ``purge``).
RETENTION = [
    ("GPS trail of trips", "7 days", "Ride Check, fare disputes"),
    ("Trip chat messages", "180 days after the trip", "Support and safety follow-up"),
    ("Notifications", "1 year", "Your inbox"),
    (
        "Safety audio recordings",
        "90 days (longer if a safety case is open)",
        "Safety investigations",
    ),
    ("Security log (logins, rate limits)", "1 year", "Protecting accounts"),
    (
        "Trips, fares, payments, invoices",
        "8 years",
        "Tax law (kept without your name after deletion)",
    ),
]


def _days() -> int:
    return int(getattr(settings, "RIDE_PULSE", {}).get("PRIVACY_RESPONSE_DAYS", 30))


# --- Consent ---------------------------------------------------------------------------------


def consents(user) -> dict[str, bool]:
    state = dict.fromkeys(ConsentPurpose.values, False)
    # Adding a trusted contact is itself the affirmative choice to share with them.
    rider = getattr(user, "rider_profile", None)
    state[ConsentPurpose.CONTACT_SHARING] = bool(rider and rider.contacts.exists())
    seen = set()
    for record in ConsentRecord.objects.filter(user=user).order_by("-created_at", "-pk"):
        if record.purpose not in seen:
            state[record.purpose] = record.granted
            seen.add(record.purpose)
    return state


def set_consent(user, purpose: str, granted: bool, *, ip: str | None = None) -> dict[str, bool]:
    if purpose not in ConsentPurpose.values:
        raise BusinessRuleViolation("Unknown purpose.", field="purpose")
    if consents(user).get(purpose) != granted:
        ConsentRecord.objects.create(
            user=user,
            purpose=purpose,
            granted=granted,
            notice_version=NOTICE_VERSION,
            ip=ip,
            created_at=timezone.now(),
        )
    return consents(user)


def has_consent(user, purpose: str) -> bool:
    return consents(user).get(purpose, False)


def consenting(user_ids, purpose: str) -> set[int]:
    """Of these users, those whose latest choice for ``purpose`` is "yes" (one query, for lists;
    contact sharing also counts riders who added a trusted contact, as ``consents`` does)."""
    latest = dict(
        ConsentRecord.objects.filter(user_id__in=list(user_ids), purpose=purpose)
        .order_by("user_id", "-created_at", "-pk")
        .distinct("user_id")
        .values_list("user_id", "granted")
    )
    if purpose == ConsentPurpose.CONTACT_SHARING:
        from apps.riders.models import TrustedContact

        with_contacts = set(
            TrustedContact.objects.filter(rider__user_id__in=list(user_ids)).values_list(
                "rider__user_id", flat=True
            )
        )
        return {uid for uid in user_ids if latest.get(uid, uid in with_contacts)}
    return {uid for uid, granted in latest.items() if granted}


# --- Requests --------------------------------------------------------------------------------


def _label(user) -> str:
    return f"{user.get_full_name() or user.email} (#{user.pk})"


@transaction.atomic
def submit(user, kind: str, *, details: str = "", now: datetime | None = None) -> DataRequest:
    now = now or timezone.now()
    if kind not in RequestKind.values:
        raise BusinessRuleViolation("Unknown request.", field="kind")
    open_kinds = [RequestStatus.RECEIVED, RequestStatus.WAITING, RequestStatus.IN_PROGRESS]
    if DataRequest.objects.filter(user=user, kind=kind, status__in=open_kinds).exists():
        raise ConflictError("You already have one of these requests open.")
    if kind == RequestKind.ERASURE:
        blockers = erasure_blockers(user)
        if blockers:
            raise BusinessRuleViolation(" ".join(blockers))
    if kind in (RequestKind.CORRECTION, RequestKind.GRIEVANCE) and len(details.strip()) < 10:
        raise BusinessRuleViolation("Tell us what needs to change.", field="details")
    request = DataRequest.objects.create(
        number=next_reference("DPR", year=timezone.localtime(now).year),
        user=user,
        user_label=_label(user),
        kind=kind,
        details=details.strip()[:2000],
        status=RequestStatus.WAITING if kind == RequestKind.ERASURE else RequestStatus.RECEIVED,
        due_at=now + timedelta(days=_days()),
        execute_after=now + COOLING_OFF if kind == RequestKind.ERASURE else None,
        created_at=now,
    )
    if kind == RequestKind.EXPORT:
        transaction.on_commit(lambda: build_export(request.pk))
    notify(
        user,
        f"We received your request ({request.number})",
        {
            RequestKind.EXPORT: "Your data file will be ready to download shortly.",
            RequestKind.ERASURE: "Your account will be deleted in 7 days. "
            "You can cancel until then.",
        }.get(kind, f"We'll reply by {timezone.localtime(request.due_at):%d %b %Y}."),
        level=Level.INFO,
        link="/privacy",
    )
    return request


def cancel(request: DataRequest, *, user) -> DataRequest:
    if request.user_id != user.pk:
        raise BusinessRuleViolation("This isn't your request.")
    if request.status not in (RequestStatus.RECEIVED, RequestStatus.WAITING):
        raise InvalidStateTransition("This request can't be cancelled any more.")
    request.status, request.completed_at = RequestStatus.CANCELLED, timezone.now()
    request.save(update_fields=["status", "completed_at"])
    return request


def resolve(request: DataRequest, *, actor, outcome: str, reject: bool = False) -> DataRequest:
    """Ops: answer a correction or grievance (or reject a request, with the reason)."""
    if request.status in (RequestStatus.COMPLETED, RequestStatus.REJECTED, RequestStatus.CANCELLED):
        raise InvalidStateTransition("This request is closed.")
    if len(outcome.strip()) < 5:
        raise BusinessRuleViolation("Write what was done.", field="outcome")
    request.status = RequestStatus.REJECTED if reject else RequestStatus.COMPLETED
    request.outcome, request.handled_by, request.completed_at = (
        outcome.strip(),
        actor,
        timezone.now(),
    )
    request.save(update_fields=["status", "outcome", "handled_by", "completed_at"])
    if request.user:
        notify(
            request.user,
            f"Update on your request {request.number}",
            outcome.strip()[:300],
            link="/privacy",
        )
    return request


# --- Access (export) -------------------------------------------------------------------------


def collect(user) -> dict:
    """Everything held about a person, grouped for reading."""
    from apps.notifications.models import Notification
    from apps.payments.models import LedgerEntry
    from apps.rides.models import Trip, TripMessage
    from apps.support.models import SupportTicket

    data: dict = {
        "generated_at": timezone.now(),
        "account": {
            "name": user.get_full_name(),
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "language": getattr(user, "language", ""),
            "joined": user.date_joined,
            "last_login": user.last_login,
        },
        "consents": consents(user),
        "consent_history": list(
            ConsentRecord.objects.filter(user=user).values(
                "purpose", "granted", "notice_version", "created_at"
            )
        ),
    }
    rider = getattr(user, "rider_profile", None)
    if rider:
        data["rider"] = {
            "rating": rider.rating,
            "emergency_contact": rider.emergency_contact_name,
            "accessibility": rider.accessibility,
            "saved_places": list(rider.saved_places.values("label", "name", "lat", "lng")),
            "trusted_contacts": list(rider.contacts.values("name", "phone", "share_mode")),
        }
        trips = Trip.objects.filter(rider=rider)
    driver = getattr(user, "driver_profile", None)
    if driver:
        data["driver"] = {
            "city": driver.city.name,
            "rating": driver.rating,
            "completed_trips": driver.completed_trips,
            "vehicles": list(
                driver.vehicles.values("make", "model", "registration_number", "year", "fuel_type")
            ),
            "documents": list(driver.documents.values("doc_type", "status", "expires_on")),
        }
        trips = Trip.objects.filter(driver=driver)
    if rider or driver:
        data["trips"] = list(
            trips.values(
                "trip_number",
                "status",
                "requested_at",
                "completed_at",
                "pickup_address",
                "dropoff_address",
                "fare_total",
                "payment_method",
            ).order_by("-requested_at")[:5000]
        )
        data["chat_messages"] = list(
            TripMessage.objects.filter(author=user).values(
                "trip__trip_number", "body", "created_at"
            )[:5000]
        )
    data["wallet_ledger"] = list(
        LedgerEntry.objects.filter(wallet__user=user)
        .values("transaction__reference", "transaction__kind", "amount", "transaction__created_at")
        .order_by("-transaction__created_at")[:5000]
    )
    data["support_tickets"] = list(
        SupportTicket.objects.filter(raised_by=user).values(
            "ticket_number",
            "category",
            "subject",
            "description",
            "status",
            "created_at",
            "resolution",
        )
    )
    data["notifications"] = list(
        Notification.objects.filter(user=user).values("title", "body", "created_at")[:500]
    )
    data["privacy_requests"] = list(
        DataRequest.objects.filter(user=user).values(
            "number", "kind", "status", "created_at", "completed_at"
        )
    )
    return data


def build_export(request_id: int) -> DataRequest:
    request = DataRequest.objects.select_related("user").get(pk=request_id)
    if request.user is None or request.status not in (
        RequestStatus.RECEIVED,
        RequestStatus.IN_PROGRESS,
    ):
        return request
    data = collect(request.user)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ride-pulse-data.json", json.dumps(data, cls=DjangoJSONEncoder, indent=1))
        archive.writestr(
            "README.txt",
            "Your Ride Pulse data, as of "
            f"{timezone.localtime(data['generated_at']):%d %b %Y %H:%M}. Each section of "
            "ride-pulse-data.json is one kind of data we hold. Questions: privacy@ridepulse.dev\n",
        )
    request.export_file.save(f"{request.number}.zip", ContentFile(buffer.getvalue()), save=False)
    now = timezone.now()
    request.status, request.completed_at, request.export_expires_at = (
        RequestStatus.COMPLETED,
        now,
        now + EXPORT_TTL,
    )
    request.outcome = "Archive ready to download for 7 days."
    request.save()
    notify(
        request.user,
        "Your data is ready to download",
        "The link works for 7 days.",
        level=Level.SUCCESS,
        link="/privacy",
    )
    return request


# --- Erasure ---------------------------------------------------------------------------------


def erasure_blockers(user) -> list[str]:
    from apps.payments.services import wallet_balance
    from apps.rides.models import ACTIVE_STATUSES, Trip

    problems = []
    rider = getattr(user, "rider_profile", None)
    driver = getattr(user, "driver_profile", None)
    if (rider and Trip.objects.filter(rider=rider, status__in=ACTIVE_STATUSES).exists()) or (
        driver and Trip.objects.filter(driver=driver, status__in=ACTIVE_STATUSES).exists()
    ):
        problems.append("Finish your current trip first.")
    balance = wallet_balance(user)
    if balance < 0:
        problems.append(f"Clear the ₹{-balance:,.2f} you owe first.")
    if user.is_staff_member and not user.is_end_user:
        problems.append("Staff accounts are closed by HR, not here.")
    from apps.workspace.powers import on_hold

    if on_hold(user):
        problems.append(
            "Your data is under a legal hold for an ongoing case, so it can't be erased yet."
        )
    return problems


@transaction.atomic
def erase(request: DataRequest, *, now: datetime | None = None) -> DataRequest:
    from django.contrib.auth.hashers import make_password

    from apps.notifications.models import Notification, PushSubscription
    from apps.rides.models import Trip, TripMessage
    from apps.support.models import TripRecordingKey

    now = now or timezone.now()
    request = (
        DataRequest.objects.select_for_update(of=("self",))
        .select_related("user")
        .get(pk=request.pk)
    )
    user = request.user
    if user is None or request.status != RequestStatus.WAITING:
        return request
    blockers = erasure_blockers(user)
    if blockers:
        request.status, request.outcome, request.completed_at = (
            RequestStatus.REJECTED,
            " ".join(blockers),
            now,
        )
        request.save(update_fields=["status", "outcome", "completed_at"])
        return request
    rider = getattr(user, "rider_profile", None)
    driver = getattr(user, "driver_profile", None)
    if rider:
        rider.saved_places.all().delete()
        rider.contacts.all().delete()
        rider.favourite_drivers.clear()
        rider.emergency_contact_name, rider.emergency_contact_phone = "", ""
        rider.ride_pin, rider.accessibility = "", []
        rider.save()
        trips = Trip.objects.filter(rider=rider)
    if driver:
        for document in driver.documents.exclude(file=""):
            document.file.delete(save=False)
        driver.documents.update(file="", number_last4="")
        trips = Trip.objects.filter(driver=driver)
    if rider or driver:
        # Keep the trip (tax records) but not where exactly the person was.
        for trip in trips.select_related("pickup_zone", "dropoff_zone"):
            Trip.objects.filter(pk=trip.pk).update(
                pickup_address=trip.pickup_zone.name if trip.pickup_zone else "",
                dropoff_address=trip.dropoff_zone.name if trip.dropoff_zone else "",
                stop_address="",
                extra_stops=[],
                share_token=None,
            )
    TripMessage.objects.filter(author=user).update(body="[deleted]", translations={})
    TripRecordingKey.objects.filter(user=user).delete()
    PushSubscription.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()
    user.first_name, user.last_name = "Deleted", "user"
    user.email = f"deleted-{user.pk}@deleted.invalid"
    user.phone = ""
    user.password = make_password(None)
    user.is_active = False
    user.save()
    request.status, request.completed_at = RequestStatus.COMPLETED, now
    request.outcome = (
        "Account deleted. Trip and payment records are kept without your name for tax law."
    )
    request.save(update_fields=["status", "completed_at", "outcome"])
    return request


def run_due(*, now: datetime | None = None) -> dict:
    """Daily: carry out erasures whose cooling-off has ended, and flag overdue requests."""
    now = now or timezone.now()
    erased = 0
    for request in DataRequest.objects.filter(
        kind=RequestKind.ERASURE, status=RequestStatus.WAITING, execute_after__lte=now
    ):
        if erase(request, now=now).status == RequestStatus.COMPLETED:
            erased += 1
    overdue = DataRequest.objects.filter(
        status__in=[RequestStatus.RECEIVED, RequestStatus.IN_PROGRESS], due_at__lt=now
    ).count()
    return {"erased": erased, "overdue": overdue}


# --- Retention -------------------------------------------------------------------------------


def purge(*, now: datetime | None = None) -> dict:
    """Delete data that has outlived its purpose (the RETENTION table)."""
    from apps.notifications.models import Notification
    from apps.reliability.models import OutboxEvent, SecurityEvent
    from apps.rides.models import TripMessage
    from apps.support.models import SafetyRecording

    now = now or timezone.now()
    counts = {
        "chat_messages": TripMessage.objects.filter(
            trip__requested_at__lt=now - timedelta(days=180)
        ).delete()[0],
        "notifications": Notification.objects.filter(
            created_at__lt=now - timedelta(days=365)
        ).delete()[0],
        "security_events": SecurityEvent.objects.filter(
            created_at__lt=now - timedelta(days=365)
        ).delete()[0],
        "outbox_events": OutboxEvent.objects.filter(
            published_at__lt=now - timedelta(days=30)
        ).delete()[0],
    }
    old_recordings = SafetyRecording.objects.filter(
        created_at__lt=now - timedelta(days=90)
    ).exclude(ticket__status__in=["OPEN", "IN_PROGRESS", "WAITING_ON_USER"])
    for recording in old_recordings:
        recording.ciphertext.delete(save=False)
    counts["safety_recordings"] = old_recordings.delete()[0]
    expired = DataRequest.objects.filter(export_expires_at__lt=now).exclude(export_file="")
    for request in expired:
        request.export_file.delete(save=False)
    counts["expired_exports"] = expired.update(export_file="")
    return counts


def queue_summary() -> dict:
    from django.db.models import Count

    open_statuses = [RequestStatus.RECEIVED, RequestStatus.WAITING, RequestStatus.IN_PROGRESS]
    return {
        "open": DataRequest.objects.filter(status__in=open_statuses).count(),
        "overdue": DataRequest.objects.filter(
            status__in=open_statuses, due_at__lt=timezone.now()
        ).count(),
        "by_kind": dict(
            DataRequest.objects.filter(status__in=open_statuses)
            .values_list("kind")
            .annotate(n=Count("pk"))
            .values_list("kind", "n")
        ),
        "response_days": _days(),
    }


def marketing_audience():
    """Riders who opted in to offers: the only people a promotion may be announced to."""
    from django.contrib.auth import get_user_model
    from django.db.models import OuterRef, Subquery

    latest = (
        ConsentRecord.objects.filter(user=OuterRef("pk"), purpose=ConsentPurpose.MARKETING)
        .order_by("-created_at", "-pk")
        .values("granted")[:1]
    )
    return (
        get_user_model()
        .objects.filter(role="RIDER", is_active=True)
        .annotate(marketing=Subquery(latest))
        .filter(marketing=True)
    )


def announce_offer(*, title: str, body: str, actor) -> int:
    """Ops: tell opted-in riders about an offer. Nobody else receives it."""
    if len(title.strip()) < 5:
        raise BusinessRuleViolation("Give the offer a title.", field="title")
    sent = 0
    for user in marketing_audience():
        notify(user, title.strip()[:160], body.strip()[:300], level=Level.INFO, link="/ride")
        sent += 1
    return sent
