from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.audit.models import AuditAction, AuditLog
from apps.core.exceptions import BusinessRuleViolation, ConflictError, DomainError
from apps.drivers import services as drivers
from apps.drivers.models import DocumentType, OnboardingStatus
from apps.geo import google, routing
from apps.payments import accounts
from apps.payments import services as payments
from apps.payments.models import Payment, PayoutStatus
from apps.pricing import services as pricing
from apps.pricing.models import PromoCode, SurgeOverride, SurgeSnapshot
from apps.rides.models import Trip
from apps.support import services as support
from apps.support.models import SafetyIncident, TicketCategory, TicketPriority

from ..conftest import T_NAGAR, make_rider, make_staff
from .helpers import book, drive_to_completion

pytestmark = pytest.mark.django_db


# --- Payments --------------------------------------------------------------------------------


def test_cash_trip_leaves_commission_as_driver_dues(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now, method="CASH"), now=now)
    # The driver holds the whole fare in cash and owes the platform everything but their share.
    assert payments.wallet_balance(driver.user) == trip.driver_earning - trip.fare_total
    balances = payments.account_balances()
    assert balances[accounts.PLATFORM_COMMISSION] == trip.platform_commission
    assert balances[accounts.GST_PAYABLE] == trip.gst_amount
    assert payments.verify_ledger()["balanced"]


def test_wallet_payment_debits_the_rider(mini, make_driver, now):
    rider = make_rider(balance=Decimal(1000))
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now, method="WALLET"), now=now)
    assert payments.wallet_balance(rider.user) == Decimal(1000) - trip.fare_total


def test_declined_card_becomes_rider_dues_but_driver_is_paid(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(
        book(rider, mini, now=now, method="CARD"), now=now, payer_reference="fail-card"
    )
    assert trip.payment_status == "DUES"
    assert payments.wallet_balance(rider.user) == -trip.fare_total
    assert payments.wallet_balance(driver.user) == trip.driver_earning
    payment = payments.pay_dues(rider.user, method="UPI")
    assert payment.status == "SUCCEEDED" and payments.wallet_balance(rider.user) == 0


def test_top_up_is_idempotent(rider):
    first = payments.top_up(rider.user, Decimal(500), method="UPI", idempotency_key="key-1")
    again = payments.top_up(rider.user, Decimal(500), method="UPI", idempotency_key="key-1")
    assert first.pk == again.pk
    assert payments.wallet_balance(rider.user) == Decimal(500)
    assert Payment.objects.filter(idempotency_key="key-1").count() == 1
    with pytest.raises(ConflictError):
        payments.top_up(rider.user, Decimal(900), method="UPI", idempotency_key="key-1")


def test_unbalanced_postings_are_rejected(rider):
    wallet = payments.ensure_wallet(rider.user)
    with pytest.raises(payments.UnbalancedTransaction):
        payments.post("TOP_UP", [(wallet, Decimal(100)), (accounts.GATEWAY, Decimal(-99))])


def test_refunds_are_capped_at_the_fare(rider, mini, make_driver, now, support_agent):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    payments.refund_to_wallet(trip, Decimal(30), reason="Goodwill", actor=support_agent)
    with pytest.raises(BusinessRuleViolation):
        payments.refund_to_wallet(trip, trip.fare_total, reason="Too much", actor=support_agent)
    assert payments.wallet_balance(rider.user) == Decimal(30)


def test_weekly_payouts_and_reversal(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    drive_to_completion(book(rider, mini, now=now), now=now)
    balance = payments.wallet_balance(driver.user)
    [payout] = payments.create_weekly_payouts(now=now + timedelta(days=7))
    assert payout.amount == balance and payments.wallet_balance(driver.user) == 0
    assert (
        payments.create_weekly_payouts(now=now + timedelta(days=7)) == []
    )  # one pending at a time
    payments.mark_payout_failed(payout, reason="Wrong IFSC")
    payout.refresh_from_db()
    assert payout.status == PayoutStatus.FAILED and payments.wallet_balance(driver.user) == balance
    assert payments.verify_ledger()["balanced"]


# --- Driver onboarding and compliance --------------------------------------------------------


def test_onboarding_moves_to_approved_only_with_every_document(chennai, mini, admin):
    driver = drivers.register_driver(
        email="new@test.dev",
        password="pw-12345!",
        first_name="New",
        city=chennai,
        license_number="TN0100001",
        license_expiry=date.today() + timedelta(days=900),
    )
    drivers.register_vehicle(
        driver,
        ride_type=mini,
        make="Tata",
        model="Tiago",
        registration_number="TN 01 XY 4321",
        year=2023,
        color="Blue",
        seats=4,
    )
    docs = {}
    for doc_type in (
        DocumentType.DRIVING_LICENSE,
        DocumentType.VEHICLE_RC,
        DocumentType.VEHICLE_INSURANCE,
    ):
        docs[doc_type] = drivers.submit_document(
            driver,
            doc_type=doc_type,
            number_last4="9999",
            expires_on=date.today() + timedelta(days=300),
        )
    driver.refresh_from_db()
    assert driver.onboarding_status == OnboardingStatus.PENDING_DOCUMENTS
    docs["PV"] = drivers.submit_document(
        driver,
        doc_type=DocumentType.POLICE_VERIFICATION,
        expires_on=date.today() + timedelta(days=300),
    )
    driver.refresh_from_db()
    assert driver.onboarding_status == OnboardingStatus.UNDER_REVIEW
    with pytest.raises(BusinessRuleViolation):
        drivers.review_document(
            docs[DocumentType.VEHICLE_RC], approve=False, reviewer=admin
        )  # reason required
    for document in docs.values():
        drivers.review_document(document, approve=True, reviewer=admin)
    driver.refresh_from_db()
    assert driver.onboarding_status == OnboardingStatus.APPROVED and driver.approved_at
    assert driver.vehicles.get().registration_number == "TN01XY4321"


def test_expired_insurance_blocks_going_online(make_driver, now):
    driver = make_driver(online=False)
    insurance = driver.documents.get(doc_type=DocumentType.VEHICLE_INSURANCE, status="APPROVED")
    insurance.expires_on = date.today() - timedelta(days=1)
    insurance.save()
    drivers.check_document_expiry()
    with pytest.raises(BusinessRuleViolation, match="Vehicle insurance"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1])


def test_dues_over_the_limit_block_going_online(rider, mini, make_driver, now):
    driver = make_driver(online=False)
    wallet = payments.ensure_wallet(driver.user)
    payments.post("ADJUSTMENT", [(wallet, Decimal(-600)), (accounts.PLATFORM_FEES, Decimal(600))])
    with pytest.raises(BusinessRuleViolation, match="dues"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1])


def test_suspended_driver_goes_offline_and_is_audited(make_driver, ops):
    driver = make_driver()
    drivers.suspend_driver(driver, reason="Fake documents", actor=ops)
    driver.refresh_from_db()
    assert (
        driver.availability == "OFFLINE" and driver.onboarding_status == OnboardingStatus.SUSPENDED
    )
    assert AuditLog.objects.filter(
        entity_type="drivers.driverprofile", entity_id=str(driver.pk), action=AuditAction.TRANSITION
    ).exists()


# --- Pricing, surge and promos ---------------------------------------------------------------


def test_manual_override_beats_computed_surge(chennai, now):
    zone = chennai.zones.get(code="t-nagar")
    SurgeSnapshot.objects.create(
        zone=zone, multiplier=Decimal("1.4"), demand=10, supply=4, computed_at=now
    )
    assert pricing.current_surge(zone, now=now) == Decimal("1.4")
    SurgeOverride.objects.create(
        zone=zone,
        multiplier=Decimal("2.0"),
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        reason="Concert",
    )
    assert pricing.current_surge(zone, now=now) == Decimal("2.0")
    assert pricing.current_surge(zone, now=now + timedelta(hours=2)) == 1  # both expired


def test_surge_recompute_reacts_to_demand(chennai, mini, make_driver, now):
    for _ in range(6):
        book(make_rider(), mini, now=now)  # no drivers online: pure demand
    snapshots = {s.zone.code: s for s in pricing.recompute_surge(city=chennai, now=now)}
    assert snapshots["t-nagar"].demand == 6 and snapshots["t-nagar"].multiplier > 1
    assert snapshots["porur"].multiplier == 1


def test_promo_rules(rider, chennai, mini, now):
    promo = PromoCode.objects.create(
        code="first50",
        description="x",
        discount_type="PERCENT",
        value=50,
        max_discount=75,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        first_ride_only=True,
    )
    assert promo.code == "FIRST50"
    assert (
        pricing.validate_promo("first50", rider=rider, city=chennai, ride_type=mini, now=now)
        == promo
    )
    rider.completed_trips = 3
    with pytest.raises(BusinessRuleViolation, match="first ride"):
        pricing.validate_promo("FIRST50", rider=rider, city=chennai, ride_type=mini, now=now)
    with pytest.raises(BusinessRuleViolation, match="invalid or has expired"):
        pricing.validate_promo(
            "FIRST50", rider=rider, city=chennai, ride_type=mini, now=now + timedelta(days=2)
        )


def test_promo_redemption_limit_is_enforced_at_completion(mini, make_driver, now):
    PromoCode.objects.create(
        code="ONCE",
        description="x",
        discount_type="FLAT",
        value=40,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        max_redemptions=1,
    )
    make_driver(now=now)
    first = drive_to_completion(book(make_rider(), mini, now=now, promo="ONCE"), now=now)
    assert first.discount_amount == Decimal(40)
    second_rider = make_rider()
    with pytest.raises(DomainError):
        book(second_rider, mini, now=now + timedelta(hours=1), promo="ONCE")


# --- Support and safety ----------------------------------------------------------------------


def test_tickets_go_to_the_least_busy_agent_with_category_priority(rider):
    busy, idle = make_staff("SUPPORT_AGENT"), make_staff("SUPPORT_AGENT")
    support.open_ticket(
        user=rider.user, category=TicketCategory.OTHER, subject="a", description="a"
    )
    first = support.open_ticket(
        user=rider.user, category=TicketCategory.OTHER, subject="b", description="b"
    )
    second = support.open_ticket(
        user=rider.user, category=TicketCategory.FARE_DISPUTE, subject="c", description="c"
    )
    assert {first.assigned_to, second.assigned_to} == {busy, idle}
    assert second.priority == TicketPriority.HIGH


def test_resolving_a_fare_dispute_with_refund(rider, mini, make_driver, now, admin):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    ticket = support.open_ticket(
        user=rider.user,
        category=TicketCategory.FARE_DISPUTE,
        subject="Overcharged",
        description="Long route",
        trip=trip,
    )
    support.reply(ticket, author=admin, body="Looking into it")
    ticket.refresh_from_db()
    assert ticket.status == "WAITING_ON_USER"
    support.resolve(ticket, actor=admin, resolution="Refunded the difference", refund_amount="25")
    assert payments.wallet_balance(rider.user) == Decimal(25)


def test_sos_alerts_the_safety_desk(rider, mini, make_driver, now, ops):
    driver = make_driver(now=now)
    trip = book(rider, mini, now=now)
    from apps.rides import dispatch

    trip = dispatch.accept_offer(trip.offers.get(), driver=driver, now=now)
    incident = support.raise_sos(trip=trip, user=rider.user, note="Help", now=now)
    assert incident.ticket.priority == TicketPriority.URGENT
    assert "SOS" in Trip.objects.get(pk=trip.pk).flags
    assert ops.notifications.filter(level="DANGER").exists()
    stranger = make_rider()
    with pytest.raises(DomainError):
        support.raise_sos(trip=trip, user=stranger.user, now=now)
    support.resolve_incident(incident, actor=ops, note="Rider safe")
    assert SafetyIncident.objects.get(pk=incident.pk).status == "RESOLVED"


# --- Analytics and audit ---------------------------------------------------------------------


def test_analytics_overview_and_series(rider, mini, make_driver, now):
    from apps.analytics import services as analytics

    make_driver(now=now)
    trip = drive_to_completion(
        book(rider, mini, now=now - timedelta(hours=2)), now=now - timedelta(hours=2)
    )
    window = {"since": now - timedelta(days=1), "until": now + timedelta(minutes=1)}
    kpis = analytics.overview(**window)
    assert kpis["requested"] == 1 and kpis["completed"] == 1
    assert kpis["gmv"] == trip.fare_total
    assert kpis["net_revenue"] == trip.fare_total - trip.gst_amount - trip.driver_earning
    series = analytics.time_series(unit="hour", **window)
    # One bucket per local clock hour the window touches (24 to 26, depending on the time).
    hour = lambda t: timezone.localtime(t).replace(minute=0, second=0, microsecond=0)  # noqa: E731
    expected = int((hour(window["until"]) - hour(window["since"])) / timedelta(hours=1)) + 1
    assert len(series) == expected and sum(p["completed"] for p in series) == 1
    assert analytics.demand_heatmap(**window)[0]["requests"] == 1


def test_audit_trail_records_field_changes(rider, ops):
    from apps.riders.services import set_blocked

    set_blocked(rider, True, reason="Chargebacks", actor=ops)
    update = AuditLog.objects.filter(
        entity_type="riders.riderprofile", entity_id=str(rider.pk), action=AuditAction.UPDATE
    ).latest("created_at")
    assert update.changes["is_blocked"] == [False, True]


# --- Google Maps integration (no network: the API client is mocked) ---------------------------


def test_routes_api_is_used_when_configured_and_cached(settings):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    response = {
        "routes": [
            {
                "distanceMeters": 7400,
                "duration": "1260s",
                "polyline": {"encodedPolyline": "_p~iF~ps|U"},
            }
        ]
    }
    with mock.patch.object(google, "_post", return_value=response) as post:
        route = routing.estimate_route(13.04, 80.23, 13.05, 80.28, timezone.now())
        routing.estimate_route(13.04, 80.23, 13.05, 80.28, timezone.now())
    assert (
        route.source == "google"
        and route.distance_km == Decimal("7.40")
        and route.duration_minutes == Decimal("21.00")
    )
    assert route.polyline == "_p~iF~ps|U"
    assert post.call_count == 1  # second call served from cache
    body = post.call_args.args[0]
    assert body["routingPreference"] == "TRAFFIC_AWARE" and body["travelMode"] == "DRIVE"


def test_routes_api_failure_falls_back_to_the_estimate(settings):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    with mock.patch.object(google, "_post", side_effect=google.GoogleMapsError("quota exceeded")):
        route = routing.estimate_route(13.04, 80.23, 13.0501, 80.2802, timezone.now())
    assert route.source == "estimate" and route.distance_km > 0


def test_trip_stores_the_google_route(rider, mini, make_driver, now, settings):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    response = {
        "routes": [
            {"distanceMeters": 7000, "duration": "1500s", "polyline": {"encodedPolyline": "abc"}}
        ]
    }
    with mock.patch.object(google, "_post", return_value=response):
        trip = book(rider, mini, now=now)
    assert trip.route_source == "google" and trip.route_polyline == "abc"
    assert trip.estimated_distance_km == Decimal("7.00")


def test_referral_bonus_is_paid_once_after_the_first_trip(mini, make_driver, now):
    from apps.riders.services import register_rider

    inviter = make_rider()
    friend = register_rider(
        email="friend@test.dev",
        password="pw-12345!",
        first_name="Arjun",
        referral_code=inviter.referral_code.lower(),  # codes are case-insensitive
    )
    assert friend.referred_by == inviter
    make_driver(now=now)

    drive_to_completion(book(friend, mini, now=now), now=now)
    friend.refresh_from_db()
    assert friend.referral_rewarded_at is not None
    assert payments.wallet_balance(inviter.user) == Decimal(50)
    assert verify_ledger_balanced()

    # A second trip (or a retry) never pays again.
    assert payments.grant_referral_bonus(friend) is None
    make_driver(now=now)
    drive_to_completion(book(friend, mini, now=now), now=now)
    assert payments.wallet_balance(inviter.user) == Decimal(50)

    # Riders without an inviter get nothing.
    loner = make_rider()
    assert payments.grant_referral_bonus(loner) is None
    with pytest.raises(BusinessRuleViolation):
        register_rider(
            email="x@test.dev", password="pw-12345!", first_name="X", referral_code="NOPE"
        )


def verify_ledger_balanced() -> bool:
    return payments.verify_ledger()["balanced"]


# --- Invoices ----------------------------------------------------------------------------------


def test_paid_trip_emails_one_invoice_with_pdf(
    rider, mini, make_driver, now, django_capture_on_commit_callbacks
):
    from django.core import mail

    make_driver(now=now)
    with django_capture_on_commit_callbacks(execute=True):
        trip = drive_to_completion(book(rider, mini, now=now), now=now, payer_reference="priya@upi")
    trip.refresh_from_db()
    assert (
        trip.invoice_number.startswith(f"INV-{trip.completed_at.year}-") and trip.invoice_emailed_at
    )
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert (
        email.to == [rider.user.email]
        and "invoice" in email.subject
        and f"₹{trip.fare_total}" in email.subject
    )
    html = email.alternatives[0][0]
    for expected in (
        trip.invoice_number,
        trip.trip_number,
        trip.vehicle.registration_display,
        "GSTIN",
        "Amount paid",
    ):
        assert expected in html
    name, pdf, kind = email.attachments[0]
    assert name.endswith(".pdf") and kind == "application/pdf" and pdf.startswith(b"%PDF")
    assert trip.invoice_number in email.body  # plain-text version too

    from apps.rides import invoices

    assert invoices.send(trip) is False  # never twice by accident
    assert len(mail.outbox) == 1


def test_invoice_waits_until_unpaid_dues_are_cleared(
    rider, mini, make_driver, now, django_capture_on_commit_callbacks
):
    from django.core import mail

    from apps.rides.models import TripPaymentStatus

    make_driver(now=now)
    with django_capture_on_commit_callbacks(execute=True):
        trip = drive_to_completion(book(rider, mini, now=now), now=now, payer_reference="fail@upi")
    trip.refresh_from_db()
    assert trip.payment_status == TripPaymentStatus.DUES and not mail.outbox
    with django_capture_on_commit_callbacks(execute=True):
        payments.pay_dues(rider.user, method="UPI", payer_reference="priya@upi")
    trip.refresh_from_db()
    assert trip.payment_status == TripPaymentStatus.PAID
    assert len(mail.outbox) == 1 and trip.invoice_number in mail.outbox[0].alternatives[0][0]


def test_phone_only_rider_gets_invoices_after_adding_an_email(
    api, mini, make_driver, now, django_capture_on_commit_callbacks
):
    from django.core import mail

    from apps.riders.services import register_rider

    phone_rider = register_rider(
        email="919840011111@phone.invalid", password=None, first_name="Ravi", phone="9840011111"
    )
    make_driver(now=now)
    with django_capture_on_commit_callbacks(execute=True):
        trip = drive_to_completion(book(phone_rider, mini, now=now), now=now)
    assert not mail.outbox  # nowhere to send it yet
    client = api(phone_rider.user)
    url = f"/api/v1/trips/{trip.pk}/email-invoice/"
    assert client.post(url).status_code == 422
    assert (
        client.patch("/api/v1/auth/me/", {"email": "Ravi@Mail.test"}, format="json").json()["email"]
        == "ravi@mail.test"
    )
    assert client.post(url).json() == {"sent_to": "ravi@mail.test"}
    assert mail.outbox[0].to == ["ravi@mail.test"]
    # The invoice can be viewed in the app, but only by the rider (and staff).
    view = client.get(f"/api/v1/trips/{trip.pk}/invoice/")
    assert (
        view.status_code == 200
        and view["Content-Type"].startswith("text/html")
        and b"Ravi" in view.content
    )
    assert api(make_rider().user).get(f"/api/v1/trips/{trip.pk}/invoice/").status_code == 404
    # Resending is limited.
    client.post(url)
    client.post(url)
    assert client.post(url).status_code == 409
    # Someone else's address can't be taken.
    assert (
        client.patch(
            "/api/v1/auth/me/", {"email": make_rider().user.email}, format="json"
        ).status_code
        == 400
    )


def test_invoice_explains_upfront_price_and_skips_synthetic_riders(mini, make_driver, now):
    from apps.riders.services import register_rider
    from apps.rides import invoices

    bot = register_rider(email="asha.rao@example.com", password=None, first_name="Asha")
    make_driver(now=now)
    trip = drive_to_completion(book(bot, mini, now=now), now=now, distance=Decimal("5.40"))
    assert not invoices.can_email(trip)  # reserved demo domain: never emailed
    html = invoices.render_html(trip)
    assert "Upfront price" in html and f"{trip.estimated_distance_km:.1f} km" in html
