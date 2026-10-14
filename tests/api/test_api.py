from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.drivers import services as drivers

from ..conftest import MARINA, T_NAGAR, make_rider, make_staff

pytestmark = pytest.mark.django_db

POINTS = {
    "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1], "address": "T. Nagar"},
    "dropoff": {"lat": MARINA[0], "lng": MARINA[1], "address": "Marina Beach"},
}


def test_health_config_and_public_cities(api):
    client = api()
    assert client.get("/api/health/").json()["database"] == "ok"
    config = client.get("/api/config/").json()
    assert config["maps"]["provider"] == "osm" and config["currency_symbol"] == "₹"
    cities = client.get("/api/v1/cities/").json()
    assert {c["slug"] for c in cities} == {"chennai", "bengaluru", "coimbatore"}


def test_pages_send_their_origin_to_map_servers(api):
    # OpenStreetMap blocks tile requests without a Referer; "same-origin" would strip it.
    response = api().get("/api/health/")
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_openapi_schema_generates(api, admin):
    response = api(admin).get("/api/schema/")
    assert response.status_code == 200
    assert b"/api/v1/trips/{id}/start/" in response.content


def test_register_login_refresh_and_logout(api):
    client = api()
    response = client.post(
        "/api/v1/auth/register/rider/",
        {
            "email": "new@rider.dev",
            "password": "Strong-pass-123",
            "first_name": "Nila",
            "phone": "9876500000",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == Role.RIDER
    token = client.post(
        "/api/v1/auth/token/",
        {"email": "new@rider.dev", "password": "Strong-pass-123"},
        format="json",
    ).json()
    assert token["user"]["email"] == "new@rider.dev"
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    assert client.get("/api/v1/auth/me/").json()["first_name"] == "Nila"
    assert (
        client.post(
            "/api/v1/auth/logout/", {"refresh": token["refresh"]}, format="json"
        ).status_code
        == 205
    )
    reuse = client.post("/api/v1/auth/token/refresh/", {"refresh": token["refresh"]}, format="json")
    assert reuse.status_code == 401  # blacklisted


def test_weak_password_and_duplicate_email_are_rejected(api, rider):
    client = api()
    weak = client.post(
        "/api/v1/auth/register/rider/",
        {"email": "a@b.dev", "password": "12345678", "first_name": "A"},
        format="json",
    )
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "validation_error"
    dup = client.post(
        "/api/v1/auth/register/rider/",
        {"email": rider.user.email, "password": "Strong-pass-123", "first_name": "A"},
        format="json",
    )
    assert dup.status_code == 422 and dup.json()["error"]["field"] == "email"


def test_full_trip_over_the_api(api, rider, make_driver):
    driver = make_driver()
    rider_client, driver_client = api(rider.user), api(driver.user)

    estimate = rider_client.post("/api/v1/fares/estimate/", POINTS, format="json").json()
    assert {o["ride_type"]["code"] for o in estimate["options"]} == {
        "BIKE",
        "AUTO",
        "MINI",
        "SEDAN",
        "SUV",
    }
    mini = next(o for o in estimate["options"] if o["ride_type"]["code"] == "MINI")
    assert mini["pickup_eta_min"] is not None

    trip = rider_client.post(
        "/api/v1/trips/", {"ride_type": "MINI", "payment_method": "UPI", **POINTS}, format="json"
    ).json()
    assert trip["status"] == "REQUESTED" and trip["estimated_fare"] == mini["fare"]["total"]
    assert trip["otp"] is None  # hidden until the driver is close

    offer = driver_client.get("/api/v1/driver/offer/").json()
    assert offer["trip_id"] == trip["id"]
    accepted = driver_client.post(f"/api/v1/driver/offers/{offer['offer_id']}/accept/").json()
    assert accepted["status"] == "DRIVER_ASSIGNED" and accepted["otp"] is None  # the driver doesn't

    driver_client.post(
        "/api/v1/driver/location/", {"lat": T_NAGAR[0], "lng": T_NAGAR[1]}, format="json"
    )
    assert (
        driver_client.post(f"/api/v1/trips/{trip['id']}/arrive/").json()["status"]
        == "DRIVER_ARRIVED"
    )
    trip = rider_client.get(f"/api/v1/trips/{trip['id']}/").json()
    assert len(trip["otp"]) == 4  # now the rider sees the PIN to read out
    bad = driver_client.post(
        f"/api/v1/trips/{trip['id']}/start/",
        {"otp": "9999" if trip["otp"] != "9999" else "1111"},
        format="json",
    )
    assert bad.status_code == 422 and bad.json()["error"]["field"] == "otp"
    assert (
        driver_client.post(
            f"/api/v1/trips/{trip['id']}/start/", {"otp": trip["otp"]}, format="json"
        ).json()["status"]
        == "IN_PROGRESS"
    )
    done = driver_client.post(
        f"/api/v1/trips/{trip['id']}/complete/", {"actual_distance_km": "6.9"}, format="json"
    ).json()
    assert done["status"] == "COMPLETED" and Decimal(done["fare_total"]) > 0

    rated = rider_client.post(
        f"/api/v1/trips/{trip['id']}/rate/", {"stars": 5, "tags": ["Polite"]}, format="json"
    ).json()
    assert rated["has_rated"] is True
    tip = rider_client.post(
        f"/api/v1/trips/{trip['id']}/tip/",
        {"amount": "30", "method": "UPI"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="tip-1",
    )
    assert tip.status_code == 200 and tip.json()["tip_amount"] == "30.00"
    receipt = rider_client.get(f"/api/v1/trips/{trip['id']}/receipt/")
    assert receipt.status_code == 200 and receipt["Content-Type"] == "application/pdf"
    assert receipt.content.startswith(b"%PDF")

    wallet = driver_client.get("/api/v1/wallet/").json()
    assert Decimal(wallet["balance"]) == Decimal(done["driver_earning"]) + 30
    earnings = driver_client.get("/api/v1/driver/earnings/?period=today").json()
    assert earnings["trips"] == 1 and Decimal(earnings["tips"]) == 30


def test_riders_only_see_their_own_trips(api, mini, make_driver):
    make_driver()
    alice, bob = make_rider(first_name="Alice"), make_rider(first_name="Bob")
    trip = (
        api(alice.user)
        .post(
            "/api/v1/trips/",
            {"ride_type": "MINI", "payment_method": "CASH", **POINTS},
            format="json",
        )
        .json()
    )
    bob_client = api(bob.user)
    assert bob_client.get("/api/v1/trips/").json()["count"] == 0
    assert bob_client.get(f"/api/v1/trips/{trip['id']}/").status_code == 404
    assert bob_client.post(f"/api/v1/trips/{trip['id']}/cancel/").status_code == 404


def test_drivers_cannot_accept_other_drivers_offers(api, rider, make_driver):
    driver = make_driver()
    other = make_driver(at=(T_NAGAR[0] + 0.05, T_NAGAR[1]))
    api(rider.user).post(
        "/api/v1/trips/", {"ride_type": "MINI", "payment_method": "UPI", **POINTS}, format="json"
    )
    offer = api(driver.user).get("/api/v1/driver/offer/").json()
    assert (
        api(other.user).post(f"/api/v1/driver/offers/{offer['offer_id']}/accept/").status_code
        == 404
    )


@pytest.mark.parametrize(
    ("role", "path", "allowed"),
    [
        (Role.SUPPORT_AGENT, "/api/v1/support/tickets/", True),
        (Role.SUPPORT_AGENT, "/api/v1/fare-rules/", True),  # read-only, for fare disputes
        (Role.SUPPORT_AGENT, "/api/v1/promos/", False),
        (Role.SUPPORT_AGENT, "/api/v1/audit-logs/", False),
        (Role.OPS_MANAGER, "/api/v1/ops/live/", True),
        (Role.OPS_MANAGER, "/api/v1/analytics/overview/", True),
        (Role.OPS_MANAGER, "/api/v1/staff/users/", False),
        (Role.ADMIN, "/api/v1/audit-logs/", True),
    ],
)
def test_role_based_access(api, role, path, allowed):
    user = make_staff(role)
    status = api(user).get(path).status_code
    assert (status == 200) is allowed, f"{role} {path} -> {status}"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/ops/live/",
        "/api/v1/drivers/",
        "/api/v1/riders/",
        "/api/v1/analytics/overview/",
        "/api/v1/payments/",
    ],
)
def test_riders_cannot_reach_staff_endpoints(api, rider, path):
    response = api(rider.user).get(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_anonymous_requests_are_rejected(api):
    assert api().get("/api/v1/trips/").status_code == 401


def test_staff_document_review_and_driver_self_service(api, chennai, ops):
    client = api()
    created = client.post(
        "/api/v1/auth/register/driver/",
        {
            "email": "d@new.dev",
            "password": "Strong-pass-123",
            "first_name": "Dev",
            "city": "chennai",
            "license_number": "TN09123",
            "license_expiry": "2031-01-01",
        },
        format="json",
    )
    assert created.status_code == 201
    driver_client = api()
    driver_client.credentials(HTTP_AUTHORIZATION=f"Bearer {created.json()['access']}")
    vehicle = driver_client.post(
        "/api/v1/driver/vehicle/",
        {
            "ride_type": "AUTO",
            "make": "Bajaj",
            "model": "RE",
            "registration_number": "TN 09 Z 1234",
            "year": 2022,
            "color": "Yellow",
            "seats": 3,
        },
        format="json",
    )
    assert vehicle.status_code == 201, vehicle.json()
    for doc in ("DRIVING_LICENSE", "VEHICLE_RC", "VEHICLE_INSURANCE", "POLICE_VERIFICATION"):
        assert (
            driver_client.post(
                "/api/v1/driver/documents/",
                {"doc_type": doc, "number_last4": "4321", "expires_on": "2030-01-01"},
                format="json",
            ).status_code
            == 200
        )
    me = driver_client.get("/api/v1/driver/me/").json()
    assert me["onboarding_status"] == "UNDER_REVIEW" and me["compliance_problems"]
    assert (
        driver_client.post(
            "/api/v1/driver/online/", {"lat": 13.04, "lng": 80.23}, format="json"
        ).status_code
        == 422
    )

    queue = api(ops).get("/api/v1/drivers/verification-queue/").json()
    assert len(queue) == 4
    for document in queue:
        api(ops).post(
            f"/api/v1/drivers/documents/{document['id']}/review/", {"approve": True}, format="json"
        )
    assert driver_client.get("/api/v1/driver/me/").json()["onboarding_status"] == "APPROVED"
    assert (
        driver_client.post(
            "/api/v1/driver/online/", {"lat": 13.04, "lng": 80.23}, format="json"
        ).json()["availability"]
        == "ONLINE"
    )


def test_validation_errors_use_the_error_envelope(api, rider):
    response = api(rider.user).post("/api/v1/trips/", {"ride_type": "MINI"}, format="json")
    body = response.json()
    assert response.status_code == 400
    assert body["error"]["code"] == "validation_error" and "pickup" in body["error"]["details"]


def test_outside_service_area_is_rejected(api, rider):
    far = {"pickup": {"lat": 28.6, "lng": 77.2}, "dropoff": {"lat": 28.7, "lng": 77.3}}
    response = api(rider.user).post("/api/v1/fares/estimate/", far, format="json")
    assert response.status_code == 422 and "doesn't operate" in response.json()["error"]["message"]


def test_place_search_and_reverse_lookup(api, rider):
    client = api(rider.user)
    results = client.get("/api/v1/places/?q=marina").json()
    assert results[0]["name"] == "Marina Beach"
    pin = client.get(f"/api/v1/places/?lat={MARINA[0]}&lng={MARINA[1]}").json()[0]
    assert pin["name"] == "Near Marina Beach"


def test_notifications_api(api, rider, make_driver):
    from apps.notifications.services import notify

    notify(rider.user, "Hello", "World")
    client = api(rider.user)
    assert client.get("/api/v1/notifications/unread-count/").json()["unread"] == 1
    assert client.post("/api/v1/notifications/mark-all-read/").json()["updated"] == 1


def test_csv_export_streams(api, ops, rider, make_driver, now):
    from apps.pricing.models import RideType
    from tests.integration.helpers import book, drive_to_completion

    make_driver(now=now)
    drive_to_completion(
        book(rider, RideType.objects.get(code="MINI"), now=now - timedelta(hours=1)),
        now=now - timedelta(hours=1),
    )
    response = api(ops).get("/api/v1/analytics/trips.csv?days=7")
    content = b"".join(response.streaming_content).decode()
    assert content.startswith("trip_number,status") and "COMPLETED" in content


def test_spa_is_served_for_client_routes(client):
    response = client.get("/ride/book")
    assert response.status_code == 200 and b"Ride Pulse" in response.content


def test_driver_go_offline_withdraws_pending_offer(api, rider, make_driver):
    driver = make_driver()
    api(rider.user).post(
        "/api/v1/trips/", {"ride_type": "MINI", "payment_method": "UPI", **POINTS}, format="json"
    )
    assert api(driver.user).post("/api/v1/driver/offline/").status_code == 200
    assert api(driver.user).get("/api/v1/driver/offer/").status_code == 204
    drivers  # noqa: B018 - imported for parity with other tests
    reverse  # noqa: B018


def test_nearby_cars_have_stable_anonymous_keys(api, make_driver, now):
    first, second = make_driver(now=now), make_driver(ride_type="AUTO", now=now)
    rider = make_rider()
    url = f"/api/v1/fares/nearby-drivers/?lat={T_NAGAR[0]}&lng={T_NAGAR[1]}"
    cars = api(rider.user).get(url).json()["drivers"]
    assert {c["ride_type"] for c in cars} == {"MINI", "AUTO"}
    # The same car keeps its key between refreshes (so the map can animate it), but the key
    # reveals nothing about which driver it is.
    again = api(rider.user).get(url).json()["drivers"]
    assert sorted(c["key"] for c in cars) == sorted(c["key"] for c in again)
    assert len({c["key"] for c in cars}) == 2
    assert not {c["key"] for c in cars} & {str(first.pk), str(second.pk)}
    assert all(set(c) == {"key", "lat", "lng", "heading", "ride_type"} for c in cars)


def test_rider_and_driver_chat_during_the_trip(api, rider, make_driver, now):
    from apps.rides import dispatch
    from apps.rides.models import TripOffer

    driver = make_driver(now=now)
    rider_client, driver_client = api(rider.user), api(driver.user)
    trip = rider_client.post(
        "/api/v1/trips/", {"ride_type": "MINI", "payment_method": "UPI", **POINTS}, format="json"
    ).json()
    url = f"/api/v1/trips/{trip['id']}/messages/"

    # No chat until a driver is on the way.
    early = rider_client.post(url, {"body": "Hello?"}, format="json")
    assert early.status_code == 409

    dispatch.accept_offer(TripOffer.objects.get(trip_id=trip["id"]), driver=driver)
    sent = rider_client.post(url, {"body": "  I'm at   the gate  "}, format="json")
    assert sent.status_code == 201 and sent.json()["body"] == "I'm at the gate"
    assert sent.json()["sender"] == "RIDER"
    assert driver_client.post(url, {"body": "2 min away"}, format="json").status_code == 201
    assert rider_client.post(url, {"body": "   "}, format="json").status_code == 400

    thread = driver_client.get(url).json()
    assert [(m["sender"], m["body"]) for m in thread] == [
        ("RIDER", "I'm at the gate"),
        ("DRIVER", "2 min away"),
    ]
    # Support staff can read the chat (safety reviews) but can't post into it.
    agent = make_staff(Role.SUPPORT_AGENT)
    assert len(api(agent).get(url).json()) == 2
    assert api(agent).post(url, {"body": "hi"}, format="json").status_code == 403
    # Nobody else can see it.
    stranger = make_rider()
    assert api(stranger.user).get(url).status_code == 404


def test_service_worker_is_served_from_the_site_root(client):
    # It must live at /sw.js (not under /static/) to control every page of the app.
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/javascript")
    assert response["Service-Worker-Allowed"] == "/"


def test_shared_trip_link_shows_the_ride_without_private_details(api, rider, make_driver, now):
    from datetime import timedelta

    from apps.rides import dispatch
    from apps.rides import services as rides
    from apps.rides.models import TripOffer

    driver = make_driver(now=now)
    trip = (
        rider.user
        and api(rider.user)
        .post(
            "/api/v1/trips/",
            {"ride_type": "MINI", "payment_method": "UPI", **POINTS},
            format="json",
        )
        .json()
    )
    dispatch.accept_offer(TripOffer.objects.get(trip_id=trip["id"]), driver=driver)

    # Only the rider can create the link; sharing twice returns the same link.
    assert api(driver.user).post(f"/api/v1/trips/{trip['id']}/share/").status_code == 403
    shared = api(rider.user).post(f"/api/v1/trips/{trip['id']}/share/").json()
    assert shared == api(rider.user).post(f"/api/v1/trips/{trip['id']}/share/").json()
    assert shared["path"] == f"/track/{shared['token']}"

    # Anyone with the link sees the ride, with no login, but nothing private.
    view = api().get(f"/api/v1/track/{shared['token']}/").json()
    assert view["status"] == "DRIVER_ASSIGNED" and view["rider_first_name"] == "Priya"
    assert view["driver"]["first_name"] == "Driver" and "Swift · TN 09" in view["vehicle"]
    assert view["driver_location"] is not None
    flat = str(view)
    pin = rides.Trip.objects.get(pk=trip["id"]).otp
    for secret in (pin, rider.user.phone, driver.user.phone, rider.user.email):
        assert secret not in flat
    assert "fare" not in view

    assert api().get("/api/v1/track/not-a-real-token/").status_code == 404
    # The link stops working an hour after the trip ends.
    trip_obj = rides.Trip.objects.get(pk=trip["id"])
    rides.cancel_trip(trip_obj, user=rider.user, reason="test")
    assert api().get(f"/api/v1/track/{shared['token']}/").status_code == 200
    later = timezone.now() + timedelta(hours=2)
    assert rides.shared_trip_view(shared["token"], now=later) is None


def test_razorpay_top_up_credits_the_wallet_exactly_once(api, rider, settings):
    import hashlib
    import hmac
    import json
    from decimal import Decimal
    from unittest import mock

    from apps.payments import razorpay
    from apps.payments.services import verify_ledger, wallet_balance

    client = api(rider.user)
    # Off until keys are configured: the app keeps using the simulated gateway.
    assert client.get("/api/config/").json()["payments"]["razorpay_key_id"] == ""
    assert client.post("/api/v1/wallet/razorpay-order/", {"amount": "200"}).status_code == 422

    settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test_abc", "s3cret"
    settings.RAZORPAY_WEBHOOK_SECRET = "hook"
    assert api().get("/api/config/").json()["payments"]["razorpay_key_id"] == "rzp_test_abc"
    with mock.patch.object(razorpay, "_post", return_value={"id": "order_T1"}) as call:
        order = client.post("/api/v1/wallet/razorpay-order/", {"amount": "200"}).json()
    assert order["order_id"] == "order_T1" and order["amount"] == 20000  # paise
    assert call.call_args.args[1]["amount"] == 20000
    assert wallet_balance(rider.user) == 0  # nothing until it's paid

    def sign(message: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

    url = "/api/v1/wallet/razorpay-confirm/"
    forged = {
        "razorpay_order_id": "order_T1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": "0" * 64,
    }
    assert client.post(url, forged).status_code == 422
    assert wallet_balance(rider.user) == 0

    good = {**forged, "razorpay_signature": sign(b"order_T1|pay_1", "s3cret")}
    assert client.post(url, good).json()["status"] == "SUCCEEDED"
    # The webhook for the same payment arrives too: still credited only once.
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_T1"}}},
        }
    ).encode()
    hook = "/api/v1/payments/razorpay/webhook/"
    assert (
        api()
        .post(hook, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="bad")
        .status_code
        == 400
    )
    ok = api().post(
        hook, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(body, "hook")
    )
    assert ok.status_code == 200
    assert client.post(url, good).status_code == 200
    assert wallet_balance(rider.user) == Decimal(200)
    assert verify_ledger()["balanced"]
    # Someone else can't confirm (or peek at) this rider's order.
    assert api(make_rider().user).post(url, good).status_code == 422


def test_metrics_endpoint_needs_its_token(api, client, settings, rider):
    settings.METRICS_TOKEN = ""
    settings.DEBUG = False
    assert client.get("/metrics").status_code == 404  # never public in production

    settings.METRICS_TOKEN = "scrape-me"
    api(rider.user).get("/api/v1/wallet/")
    assert client.get("/metrics", HTTP_AUTHORIZATION="Bearer wrong").status_code == 404
    body = client.get("/metrics", HTTP_AUTHORIZATION="Bearer scrape-me").content.decode()
    assert 'ridepulse_http_requests_total{method="GET",route="wallet-list",status="200"}' in body
    assert 'ridepulse_trips_active{status="REQUESTED"} 0' in body
    assert "ridepulse_ledger_balanced 1" in body
    assert "ridepulse_http_request_duration_seconds_bucket" in body


def test_phone_otp_login_signup_and_abuse_limits(api, settings):
    from datetime import timedelta

    from apps.accounts.models import PhoneOTP

    settings.DEBUG = True  # the console SMS backend hands the code back in development
    client = api()

    # A brand-new number: verify, then sign up with just a name.
    sent = client.post("/api/v1/auth/otp/request/", {"phone": "+91 98400-12345"}).json()
    assert sent["phone"] == "9840012345" and len(sent["debug_code"]) == 6
    stored = PhoneOTP.objects.get(phone="9840012345")
    assert sent["debug_code"] not in stored.code_hash  # only a keyed hash is stored

    wrong = "000000" if sent["debug_code"] != "000000" else "111111"
    bad = client.post("/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": wrong})
    assert bad.status_code == 422 and "4 tries left" in bad.json()["error"]["message"]
    verified = client.post(
        "/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": sent["debug_code"]}
    ).json()
    assert verified["new_user"] is True
    # The code can't be used twice.
    again = client.post(
        "/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": sent["debug_code"]}
    )
    assert again.status_code == 422
    signed_up = client.post(
        "/api/v1/auth/otp/signup/",
        {"signup_token": verified["signup_token"], "first_name": "Divya"},
    )
    assert signed_up.status_code == 201
    assert signed_up.json()["user"]["role"] == "RIDER" and signed_up.json()["access"]

    # Next time the same number signs straight in.
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(minutes=1))
    code = client.post("/api/v1/auth/otp/request/", {"phone": "9840012345"}).json()["debug_code"]
    login = client.post("/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": code}).json()
    assert login["new_user"] is False and login["user"]["first_name"] == "Divya"

    # Resend limits: one code per 30 s...
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(minutes=1))
    assert client.post("/api/v1/auth/otp/request/", {"phone": "9840012345"}).status_code == 200
    assert client.post("/api/v1/auth/otp/request/", {"phone": "9840012345"}).status_code == 409
    # ...five wrong guesses burn the code...
    for _ in range(5):
        client.post("/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": "999999"})
    assert PhoneOTP.objects.filter(phone="9840012345", consumed_at__isnull=True).count() == 0
    # ...and expired codes don't work.
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(minutes=1))
    code = client.post("/api/v1/auth/otp/request/", {"phone": "9840012345"}).json()["debug_code"]
    PhoneOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert (
        client.post("/api/v1/auth/otp/verify/", {"phone": "9840012345", "code": code}).status_code
        == 422
    )

    assert client.post("/api/v1/auth/otp/request/", {"phone": "12345"}).status_code == 422
    # Staff don't sign in by SMS.
    agent = make_staff(Role.SUPPORT_AGENT)
    agent.phone = "9000000001"
    agent.save()
    code = client.post("/api/v1/auth/otp/request/", {"phone": "9000000001"}).json()["debug_code"]
    assert (
        client.post("/api/v1/auth/otp/verify/", {"phone": "9000000001", "code": code}).status_code
        == 422
    )

    # Without DEBUG the code is never returned.
    settings.DEBUG = False
    assert (
        "debug_code" not in client.post("/api/v1/auth/otp/request/", {"phone": "9123456780"}).json()
    )


def test_riders_and_drivers_call_through_a_masked_number(api, rider, make_driver, now, settings):
    from unittest import mock

    from apps.rides import calls, dispatch
    from apps.rides.models import TripOffer

    driver = make_driver(now=now)
    rider_client, driver_client = api(rider.user), api(driver.user)
    trip = rider_client.post(
        "/api/v1/trips/", {"ride_type": "MINI", "payment_method": "UPI", **POINTS}, format="json"
    ).json()
    url = f"/api/v1/trips/{trip['id']}/call/"
    assert rider_client.post(url).status_code == 422  # no driver yet

    dispatch.accept_offer(TripOffer.objects.get(trip_id=trip["id"]), driver=driver)
    # Neither side can see the other's real number...
    seen_by_rider = rider_client.get(f"/api/v1/trips/{trip['id']}/").json()
    seen_by_driver = driver_client.get(f"/api/v1/trips/{trip['id']}/").json()
    assert seen_by_rider["driver"]["phone"] is None and seen_by_driver["rider"]["phone"] is None
    assert driver.user.phone not in str(seen_by_rider) and rider.user.phone not in str(
        seen_by_driver
    )
    # ...but support staff can.
    agent = make_staff(Role.SUPPORT_AGENT)
    assert (
        api(agent).get(f"/api/v1/trips/{trip['id']}/").json()["rider"]["phone"] == rider.user.phone
    )

    demo = rider_client.post(url).json()
    assert demo["mode"] == "demo" and "No call was placed" in demo["message"]

    settings.EXOTEL_SID, settings.EXOTEL_API_KEY = "ridepulse1", "key"
    settings.EXOTEL_API_TOKEN, settings.EXOTEL_CALLER_ID = "token", "08047180000"
    with mock.patch.object(calls, "_exotel_connect", return_value="CA123") as connect:
        live = driver_client.post(url).json()
    assert live["mode"] == "exotel" and "Pick up" in live["message"]
    connect.assert_called_once_with(driver.user.phone, rider.user.phone)  # bridged server-side
    assert api(make_rider().user).post(url).status_code == 404  # strangers can't call


def test_web_push_reaches_subscribed_devices(
    api, rider, make_driver, settings, now, django_capture_on_commit_callbacks
):
    import json
    from io import StringIO
    from unittest import mock

    from django.core.management import call_command
    from pywebpush import WebPushException

    from apps.notifications import push
    from apps.notifications.models import PushSubscription
    from apps.notifications.services import notify
    from apps.pricing.models import RideType
    from tests.integration.helpers import book

    keys = StringIO()
    call_command("generate_vapid_keys", stdout=keys)
    pairs = dict(line.split("=", 1) for line in keys.getvalue().split())
    settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY = (
        pairs["VAPID_PUBLIC_KEY"],
        pairs["VAPID_PRIVATE_KEY"],
    )
    assert len(pairs["VAPID_PUBLIC_KEY"]) == 87  # 65-byte uncompressed P-256 point, base64url
    assert api().get("/api/config/").json()["push"]["vapid_public_key"] == settings.VAPID_PUBLIC_KEY

    device = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}
    assert (
        api(rider.user).post("/api/v1/push/subscription/", device, format="json").status_code == 204
    )
    assert PushSubscription.objects.get().user == rider.user

    with (
        mock.patch("pywebpush.webpush") as webpush,
        django_capture_on_commit_callbacks(execute=True),
    ):
        notify(rider.user, "Your driver has arrived", "Meet at T. Nagar", link="/ride/trips/1/")
        # Drivers get urgent offer pushes that expire with the offer.
        driver = make_driver(now=now)
        api(driver.user).post(
            "/api/v1/push/subscription/",
            {**device, "endpoint": "https://push.example.com/drv"},
            format="json",
        )
        book(rider, RideType.objects.get(code="MINI"), now=now)
    sent = [
        json.loads(c.kwargs["data"])
        | {"ttl": c.kwargs["ttl"], "urgency": c.kwargs["headers"]["Urgency"]}
        for c in webpush.call_args_list
    ]
    assert {
        "title": "Your driver has arrived",
        "body": "Meet at T. Nagar",
        "url": "/ride/trips/1/",
        "tag": "",
    }.items() <= sent[0].items()
    offer = next(s for s in sent if s["tag"] == "offer")
    assert (
        offer["title"].startswith("New Mini request")
        and offer["urgency"] == "high"
        and offer["ttl"] <= 20
    )

    # A device that uninstalled the app is forgotten.
    gone = WebPushException("Gone", response=mock.Mock(status_code=410))
    with mock.patch("pywebpush.webpush", side_effect=gone):
        assert push.send(rider.user.pk, title="x") == 0
    assert not PushSubscription.objects.filter(user=rider.user).exists()


def test_split_fare_with_friends(api, rider, make_driver, now):
    from decimal import Decimal

    from apps.payments.services import verify_ledger, wallet_balance
    from apps.rides import services as rides
    from tests.integration.helpers import book, drive_to_completion

    friend_a, friend_b = make_rider(), make_rider()
    make_driver(now=now)
    trip = drive_to_completion(
        book(rider, rides.RideType.objects.get(code="MINI"), now=now), now=now
    )
    client = api(rider.user)
    url = f"/api/v1/trips/{trip.pk}/split/"

    assert client.post(url, {"phones": ["9999999999"]}, format="json").status_code == 422  # unknown
    sent = client.post(
        url, {"phones": [friend_a.user.phone, "+91 " + friend_b.user.phone]}, format="json"
    ).json()
    share = (trip.fare_total / 3).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    assert [s["amount"] for s in sent] == [str(share)] * 2
    assert (
        client.post(url, {"phones": [friend_a.user.phone]}, format="json").status_code == 409
    )  # once

    # Friend A pays by UPI: the money lands in the rider's wallet.
    before = wallet_balance(rider.user)
    a_split = api(friend_a.user).get("/api/v1/fare-splits/").json()["results"][0]
    assert a_split["rider_name"] == rider.name and a_split["status"] == "REQUESTED"
    assert a_split["incoming"] is True  # sent to friend A to pay
    assert all(not row["incoming"] for row in client.get("/api/v1/fare-splits/").json()["results"])
    paid = (
        api(friend_a.user)
        .post(
            f"/api/v1/fare-splits/{a_split['id']}/pay/",
            {"method": "UPI", "payer_reference": "a@upi"},
        )
        .json()
    )
    assert paid["status"] == "PAID" and wallet_balance(rider.user) == before + share
    assert (
        api(friend_a.user)
        .post(f"/api/v1/fare-splits/{a_split['id']}/pay/", {"method": "UPI"})
        .status_code
        == 409
    )

    # Friend B declines; the rider sees both outcomes.
    b_split = api(friend_b.user).get("/api/v1/fare-splits/").json()["results"][0]
    assert (
        api(friend_b.user).post(f"/api/v1/fare-splits/{b_split['id']}/decline/").json()["status"]
        == "DECLINED"
    )
    assert sorted(s["status"] for s in client.get(url).json()) == ["DECLINED", "PAID"]
    # Strangers can't see or pay other people's splits.
    assert (
        api(make_rider().user)
        .post(f"/api/v1/fare-splits/{a_split['id']}/pay/", {"method": "UPI"})
        .status_code
        == 404
    )
    assert verify_ledger()["balanced"]


def test_lost_and_found(api, rider, make_driver, now):
    from apps.rides import services as rides
    from apps.rides.models import Trip
    from apps.support.models import SupportTicket, TicketStatus
    from tests.integration.helpers import book, drive_to_completion

    driver = make_driver(now=now)
    trip = drive_to_completion(
        book(rider, rides.RideType.objects.get(code="MINI"), now=now), now=now
    )
    rider_client, driver_client = api(rider.user), api(driver.user)
    url = f"/api/v1/trips/{trip.pk}/lost-item/"
    call = f"/api/v1/trips/{trip.pk}/call/"

    # Long after the ride, calls are closed until a lost item is reported.
    Trip.objects.filter(pk=trip.pk).update(completed_at=timezone.now() - timedelta(days=2))
    assert rider_client.get(url).status_code == 204
    assert rider_client.post(call).status_code == 422
    assert driver_client.post(url, {"description": "bag"}).status_code == 403  # rider only
    assert rider_client.post(url, {"description": "x"}).status_code == 422
    item = rider_client.post(url, {"description": "Black  backpack"}).json()
    assert item["status"] == "REPORTED" and item["description"] == "Black backpack"
    assert rider_client.post(url, {"description": "again"}).status_code == 409
    ticket = SupportTicket.objects.get(trip=trip)
    assert ticket.category == "LOST_ITEM" and ticket.priority == "HIGH"
    assert rider_client.post(call).status_code == 200  # the call window reopened

    # The driver sees it, finds it, and they arrange the hand-back.
    waiting = driver_client.get("/api/v1/driver/lost-items/").json()
    assert [w["id"] for w in waiting] == [item["id"]]
    assert rider_client.post(f"{url}answer/", {"found": True}).status_code == 403
    found = driver_client.post(f"{url}answer/", {"found": True, "note": "On the seat"}).json()
    assert found["status"] == "FOUND" and found["driver_note"] == "On the seat"
    returned = rider_client.post(f"{url}returned/").json()
    assert returned["status"] == "RETURNED"
    ticket.refresh_from_db()
    assert ticket.status == TicketStatus.RESOLVED
    assert driver_client.get("/api/v1/driver/lost-items/").json() == []
    assert rider_client.post(call).status_code == 422  # closed again

    # Too late to report after 7 days.
    other = drive_to_completion(
        book(rider, rides.RideType.objects.get(code="MINI"), now=now), now=now
    )
    Trip.objects.filter(pk=other.pk).update(completed_at=timezone.now() - timedelta(days=8))
    assert (
        rider_client.post(
            f"/api/v1/trips/{other.pk}/lost-item/", {"description": "phone"}
        ).status_code
        == 422
    )
