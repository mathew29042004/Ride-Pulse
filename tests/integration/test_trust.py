"""Trust and compliance: consent and data rights, appeals, insurance claims, CSAT, saved
replies and the help centre."""

import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.drivers.models import OnboardingStatus
from apps.drivers.services import suspend_driver
from apps.payments import services as payments
from apps.riders.models import TrustedContact
from apps.riders.services import set_blocked
from apps.rides import safety
from apps.support.services import open_ticket, resolve
from apps.trust import appeals, claims, privacy, support_quality
from apps.trust.models import ConsentPurpose, DataRequest, HelpArticle, Macro, RequestStatus

from ..conftest import make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


# --- Consent and data rights -----------------------------------------------------------------


def test_consent_is_opt_in_recorded_and_enforced(mini, make_driver, now, ops):
    rider = make_rider()
    assert privacy.consents(rider.user) == {"MARKETING": False, "CONTACT_SHARING": False}
    privacy.set_consent(rider.user, ConsentPurpose.MARKETING, True)
    assert privacy.marketing_audience().filter(pk=rider.user.pk).exists()
    assert privacy.announce_offer(title="Weekend offer", body="20% off", actor=ops) == 1
    privacy.set_consent(rider.user, ConsentPurpose.MARKETING, False)
    assert privacy.announce_offer(title="Weekend offer", body="20% off", actor=ops) == 0
    assert rider.user.consents.count() == 2  # the full history is kept

    # Adding a contact turns sharing on; switching it off stops the SMS.
    TrustedContact.objects.create(rider=rider, name="Amma", phone="9876501234", share_mode="ALWAYS")
    assert privacy.has_consent(rider.user, ConsentPurpose.CONTACT_SHARING)
    privacy.set_consent(rider.user, ConsentPurpose.CONTACT_SHARING, False)
    from apps.rides import dispatch
    from apps.rides import services as rides

    from .helpers import pending_offer

    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    from apps.drivers.services import update_location

    update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    assert safety.share_with_contacts(trip.pk, now=now) == 0


def test_export_contains_the_persons_data(
    mini, make_driver, now, django_capture_on_commit_callbacks
):
    rider = make_rider()
    make_driver(now=now)
    drive_to_completion(book(rider, mini, now=now), now=now)
    with django_capture_on_commit_callbacks(execute=True):
        request = privacy.submit(rider.user, "EXPORT")
    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED and request.export_file
    with zipfile.ZipFile(io.BytesIO(request.export_file.read())) as archive:
        data = json.loads(archive.read("ride-pulse-data.json"))
    assert data["account"]["email"] == rider.user.email
    assert len(data["trips"]) == 1 and data["trips"][0]["fare_total"]
    with pytest.raises(ConflictError):
        privacy.submit(rider.user, "CORRECTION", details="Fix my name please")
        privacy.submit(rider.user, "CORRECTION", details="Fix my name please")


def test_erasure_waits_then_erases_but_keeps_tax_records(mini, make_driver, now):
    rider = make_rider(first_name="Meena")
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    request = privacy.submit(rider.user, "ERASURE", now=now)
    assert request.status == RequestStatus.WAITING
    assert privacy.run_due(now=now + timedelta(days=1))["erased"] == 0  # still cooling off
    assert privacy.run_due(now=now + timedelta(days=8))["erased"] == 1
    rider.user.refresh_from_db()
    assert (
        rider.user.first_name == "Deleted" and rider.user.phone == "" and not rider.user.is_active
    )
    trip.refresh_from_db()
    assert trip.fare_total > 0  # kept for tax law
    assert trip.pickup_address == (trip.pickup_zone.name if trip.pickup_zone else "")
    assert payments.verify_ledger()["balanced"]


def test_erasure_refused_while_money_is_owed(mini, now):
    rider = make_rider()
    payments.post(
        "TRIP_FARE",
        [(payments.ensure_wallet(rider.user), Decimal("-50")), ("platform:fees", Decimal("50"))],
    )
    with pytest.raises(BusinessRuleViolation, match="you owe"):
        privacy.submit(rider.user, "ERASURE")


# --- Appeals ---------------------------------------------------------------------------------


def test_appeal_needs_a_different_reviewer_and_reverses(make_driver, now, admin, ops):
    driver = make_driver(online=False)
    suspend_driver(driver, reason="Complaints about rude behaviour", actor=ops)
    appeal = appeals.submit(
        driver.user,
        "DRIVER_SUSPENSION",
        statement="I was not rude; the rider refused to pay the toll they agreed to.",
    )
    assert appeal.original_decided_by == ops
    with pytest.raises(ActionNotPermitted, match="Someone else"):
        appeals.decide(appeal, reviewer=ops, uphold=True, note="Reviewed the chat log, fine.")
    appeals.decide(
        appeal,
        reviewer=admin,
        uphold=True,
        note="The chat log shows the toll dispute; reinstating.",
    )
    driver.refresh_from_db()
    assert driver.onboarding_status == OnboardingStatus.APPROVED


def test_rider_block_appeal_denied_keeps_the_block(admin, ops):
    rider = make_rider()
    set_blocked(rider, True, reason="Abusive messages to drivers", actor=ops)
    appeal = appeals.submit(
        rider.user, "RIDER_BLOCK", statement="I'm sorry, I was upset about a long wait that day."
    )
    appeals.decide(
        appeal,
        reviewer=admin,
        uphold=False,
        note="Three separate reports; the block stays for now.",
    )
    rider.refresh_from_db()
    assert rider.is_blocked and appeal.status == "OPEN"  # local copy; DB is decided
    with pytest.raises(BusinessRuleViolation, match="isn't blocked"):
        appeals.submit(
            make_rider().user,
            "RIDER_BLOCK",
            statement="Something long enough to pass the length check.",
        )


# --- Claims ----------------------------------------------------------------------------------


def test_claim_paid_by_the_insurer_into_the_wallet(mini, make_driver, now, admin):
    rider = make_rider()
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    with pytest.raises(BusinessRuleViolation, match="Up to"):
        claims.file_claim(
            trip,
            user=rider.user,
            kind="PROPERTY",
            amount=Decimal(50000),
            description="My phone screen cracked when the car braked hard.",
        )
    claim = claims.file_claim(
        trip,
        user=rider.user,
        kind="PROPERTY",
        amount=Decimal(6000),
        description="My phone screen cracked when the car braked hard.",
    )
    claims.start_review(claim, reviewer=admin)
    before = payments.wallet_balance(rider.user)
    claims.decide(
        claim,
        reviewer=admin,
        approve=True,
        amount=Decimal(4500),
        note="Repair quote accepted, less the excess.",
    )
    assert payments.wallet_balance(rider.user) == before + Decimal(4500)
    assert payments.account_balances()["external:insurer"] == Decimal(-4500)
    assert payments.verify_ledger()["balanced"]
    with pytest.raises(ActionNotPermitted):
        claims.file_claim(
            trip,
            user=make_rider().user,
            kind="PROPERTY",
            amount=Decimal(10),
            description="Not my trip but trying anyway, long enough text.",
        )


def test_claim_window(mini, make_driver, now):
    rider = make_rider()
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    with pytest.raises(BusinessRuleViolation, match="7 days"):
        claims.file_claim(
            trip,
            user=rider.user,
            kind="INJURY",
            amount=Decimal(500),
            description="Twisted my ankle getting out of the car at the drop.",
            now=timezone.now() + timedelta(days=9),
        )


# --- Support quality -------------------------------------------------------------------------


def test_csat_macros_and_help_centre(support_agent):
    rider = make_rider(first_name="Divya")
    ticket = open_ticket(
        user=rider.user,
        category="PAYMENT",
        subject="Charged twice",
        description="Two UPI debits for one ride.",
    )
    with pytest.raises(Exception, match="once the ticket is resolved"):
        support_quality.rate(ticket, user=rider.user, score=5)
    macro = Macro.objects.create(
        title="Double charge", body="Hi {name}, about {ticket}: refunded.", category="PAYMENT"
    )
    message = support_quality.use_macro(macro, ticket, agent=support_agent)
    assert message.body == f"Hi Divya, about {ticket.ticket_number}: refunded."
    ticket = resolve(ticket, actor=support_agent, resolution="Refunded the duplicate.")
    support_quality.rate(ticket, user=rider.user, score=5, comment="Fast!")
    with pytest.raises(ConflictError):
        support_quality.rate(ticket, user=rider.user, score=1)
    assert (
        support_quality.csat_by_agent([support_agent.pk], timezone.now() - timedelta(days=1))[
            support_agent.pk
        ]["csat"]
        == 100
    )

    article = HelpArticle.objects.create(
        slug="refunds",
        title="How refunds work",
        body="Instantly to your wallet.",
        category="Payments",
        keywords="refund money",
    )
    assert list(support_quality.search("refund")) == [article]
    voter = make_rider()
    support_quality.vote(
        article, user=voter.user, helpful=True, now=timezone.now() - timedelta(hours=2)
    )
    assert support_quality.help_stats()["deflections"] == 1  # no ticket within the hour


def test_privacy_api_and_ops_permissions(api, ops):
    rider = make_rider()
    client = api(rider.user)
    body = client.get("/api/v1/me/privacy/").json()
    assert body["consents"]["MARKETING"] is False and body["retention"]
    client.post("/api/v1/me/privacy/", {"purpose": "MARKETING", "granted": True})
    assert client.get("/api/v1/me/privacy/").json()["consents"]["MARKETING"] is True
    made = client.post(
        "/api/v1/me/privacy/requests/",
        {"kind": "GRIEVANCE", "details": "Please stop sending me offers by SMS."},
    ).json()
    assert made["status"] == "RECEIVED"
    assert api(ops).get("/api/v1/ops/trust/overview/").json()["privacy"]["open"] == 1
    assert (
        api(make_staff(Role.FLEET_EXECUTIVE)).get("/api/v1/ops/trust/overview/").status_code == 403
    )
    assert DataRequest.objects.get(number=made["number"]).due_at > timezone.now() + timedelta(
        days=29
    )
