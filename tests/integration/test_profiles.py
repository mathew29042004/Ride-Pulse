"""Family and business profiles: one payer for several riders."""

from decimal import Decimal

import pytest

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.notifications.models import Notification
from apps.payments import services as payments
from apps.riders import profiles
from apps.riders.models import MemberStatus

from ..conftest import make_rider
from .helpers import drive_to_completion

pytestmark = pytest.mark.django_db


def funded_owner(amount=1000):
    owner = make_rider(first_name="Lakshmi")
    payments.top_up(owner.user, Decimal(amount), method="UPI", payer_reference="owner@upi")
    return owner


def family_with(member, owner):
    profile = profiles.create_profile(owner, kind="FAMILY", name="Raman family")
    invitation = profiles.invite(profile, user=owner.user, phone=member.user.phone)
    profiles.respond(invitation, user=member.user, accept=True)
    return profile


def test_family_member_ride_is_paid_by_the_owner(mini, make_driver, now):
    owner, member = funded_owner(), make_rider(first_name="Priya")
    profile = family_with(member, owner)
    make_driver(now=now)
    before_owner, before_member = (
        payments.wallet_balance(owner.user),
        payments.wallet_balance(member.user),
    )
    trip = drive_to_completion(book_on(member, mini, now, profile), now=now)
    assert trip.payment_profile == profile and trip.payment_status == "PAID"
    assert payments.wallet_balance(owner.user) == before_owner - trip.fare_total
    assert payments.wallet_balance(member.user) == before_member  # untouched
    assert Notification.objects.filter(user=owner.user, title__startswith="Priya").exists()
    assert payments.verify_ledger()["balanced"]


def book_on(rider, mini, now, profile, purpose=""):
    from apps.rides import services as rides

    from ..conftest import MARINA, T_NAGAR

    return rides.request_trip(
        rider=rider,
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        payment_profile=profile,
        trip_purpose=purpose,
        now=now,
    )


def test_invitations_and_permissions(mini, now):
    owner, member, stranger = funded_owner(), make_rider(), make_rider()
    profile = profiles.create_profile(owner, kind="FAMILY", name="Family")
    with pytest.raises(BusinessRuleViolation, match="No Ride Pulse rider"):
        profiles.invite(profile, user=owner.user, phone="9999999999")
    with pytest.raises(ActionNotPermitted):
        profiles.invite(profile, user=stranger.user, phone=member.user.phone)
    invitation = profiles.invite(profile, user=owner.user, phone=member.user.phone)
    with pytest.raises(ConflictError):
        profiles.invite(profile, user=owner.user, phone=member.user.phone)
    with pytest.raises(ActionNotPermitted):  # invited isn't joined yet
        book_on(member, mini, now, profile)
    with pytest.raises(ActionNotPermitted):
        profiles.respond(invitation, user=stranger.user, accept=True)
    profiles.respond(invitation, user=member.user, accept=True)
    assert list(profiles.usable_profiles(member)) == [profile]
    assert list(profiles.usable_profiles(stranger)) == []


def test_monthly_limit_and_owner_balance(mini, make_driver, now):
    owner, member = funded_owner(amount=150), make_rider()
    profile = family_with(member, owner)
    make_driver(now=now)
    membership = profile.members.get(rider=member)
    profiles.update_member(membership, user=owner.user, monthly_limit=Decimal(50))
    with pytest.raises(BusinessRuleViolation, match="monthly limit"):
        book_on(member, mini, now, profile)
    profiles.update_member(membership, user=owner.user, monthly_limit=None)
    with pytest.raises(BusinessRuleViolation, match="top up"):  # ₹150 doesn't cover a Mini
        payments_trip = book_on(member, mini, now, profile)
        assert payments_trip.estimated_fare > 150
    profiles.update_member(membership, user=owner.user, remove=True)
    assert profile.members.get(rider=member).status == MemberStatus.REMOVED


def test_business_needs_a_purpose_and_bills_on_credit(mini, make_driver, now):
    company, employee = make_rider(first_name="Acme"), make_rider()
    profile = profiles.create_profile(
        company, kind="BUSINESS", name="Acme Pvt Ltd", gstin="33ABCDE1234F1Z5"
    )
    profile.credit_limit = Decimal(5000)
    profile.save()
    invitation = profiles.invite(profile, user=company.user, phone=employee.user.phone)
    profiles.respond(invitation, user=employee.user, accept=True)
    make_driver(now=now)
    with pytest.raises(BusinessRuleViolation, match="purpose"):
        book_on(employee, mini, now, profile)
    trip = drive_to_completion(book_on(employee, mini, now, profile, "Client meeting"), now=now)
    assert trip.trip_purpose == "Client meeting" and trip.payment_status == "PAID"
    assert payments.wallet_balance(company.user) == -trip.fare_total  # on credit
    statement = profiles.statement(profile, user=company.user)
    assert statement["rides"] == 1 and statement["total"] == trip.fare_total
    assert statement["trips"][0]["purpose"] == "Client meeting"
    with pytest.raises(ActionNotPermitted):
        profiles.statement(profile, user=employee.user)


def test_api(api, mini, make_driver, now):
    owner, member = funded_owner(), make_rider()
    owner_client, member_client = api(owner.user), api(member.user)
    created = owner_client.post(
        "/api/v1/rider/profiles/", {"kind": "FAMILY", "name": "Raman family"}, format="json"
    ).json()
    pid = created["id"]
    assert created["role"] == "OWNER"
    owner_client.post(f"/api/v1/rider/profiles/{pid}/invite/", {"phone": member.user.phone})
    invited = member_client.get("/api/v1/rider/profiles/").json()
    assert invited[0]["role"] == "INVITED"
    member_client.post(f"/api/v1/rider/profiles/{pid}/respond/", {"accept": True})
    assert member_client.get("/api/v1/rider/profiles/").json()[0]["role"] == "MEMBER"
    members = owner_client.get(f"/api/v1/rider/profiles/{pid}/").json()["members"]
    assert members[0]["status"] == "ACTIVE"

    make_driver(now=now)
    from ..conftest import MARINA, T_NAGAR

    trip = member_client.post(
        "/api/v1/trips/",
        {
            "ride_type": "MINI",
            "payment_method": "UPI",
            "payment_profile": pid,
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
            "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
        },
        format="json",
    ).json()
    assert trip["payment_profile_name"] == "Raman family" and trip["payment_method"] == "WALLET"
    stranger = api(make_rider().user).post(
        "/api/v1/trips/",
        {
            "ride_type": "MINI",
            "payment_method": "UPI",
            "payment_profile": pid,
            "pickup": {"lat": T_NAGAR[0], "lng": T_NAGAR[1]},
            "dropoff": {"lat": MARINA[0], "lng": MARINA[1]},
        },
        format="json",
    )
    assert stranger.status_code == 403
    csv = owner_client.get(f"/api/v1/rider/profiles/{pid}/statement/?export=csv")
    assert csv.status_code == 200 and b"trip_number" in csv.content
