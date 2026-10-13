"""Shared fixtures. Tests run against a real PostgreSQL test database (the schema relies on
partial unique indexes, ArrayField, BRIN indexes and generate_series)."""

import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.drivers import services as drivers
from apps.drivers.models import REQUIRED_DOCUMENTS
from apps.geo.models import City
from apps.notifications import services as notifications
from apps.payments import services as payments
from apps.pricing.models import RideType
from apps.realtime import broadcast
from apps.riders.services import register_rider

T_NAGAR = (13.0418, 80.2341)
MARINA = (13.0500, 80.2824)
ADYAR = (13.0012, 80.2565)

_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _quiet():
    """Keep tests fast and deterministic: no WebSocket fan-out unless a test asks for it."""
    with broadcast.muted():
        yield


@pytest.fixture
def now():
    return timezone.now()


@pytest.fixture
def chennai(db):
    return City.objects.get(slug="chennai")


@pytest.fixture
def mini(db):
    return RideType.objects.get(code="MINI")


@pytest.fixture
def sedan(db):
    return RideType.objects.get(code="SEDAN")


def make_staff(role: str, email: str | None = None):
    n = next(_seq)
    return get_user_model().objects.create_user(
        email or f"{role.lower()}{n}@test.dev",
        "pw-12345!",
        role=role,
        first_name=role.title(),
        last_name=str(n),
    )


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_superuser(
        "admin@test.dev", "pw-12345!", first_name="Ada", last_name="Admin"
    )


@pytest.fixture
def ops(db):
    return make_staff(Role.OPS_MANAGER)


@pytest.fixture
def support_agent(db):
    return make_staff(Role.SUPPORT_AGENT)


def make_rider(*, balance: Decimal | None = None, first_name: str = "Priya"):
    n = next(_seq)
    rider = register_rider(
        email=f"rider{n}@test.dev",
        password="pw-12345!",
        first_name=first_name,
        last_name=f"R{n}",
        phone=f"98765{n:05d}",
    )
    if balance:
        payments.top_up(rider.user, balance, method="UPI")
    return rider


@pytest.fixture
def rider(db):
    return make_rider()


@pytest.fixture
def make_driver(db, chennai, admin):
    """Factory for approved drivers, optionally already online at a location."""

    def factory(*, ride_type="MINI", at=None, online=True, city=None, now=None):
        n = next(_seq)
        driver = drivers.register_driver(
            email=f"driver{n}@test.dev",
            password="pw-12345!",
            first_name="Driver",
            last_name=str(n),
            phone=f"91234{n:05d}",
            city=city or chennai,
            license_number=f"TN09{n:010d}",
            license_expiry=date.today() + timedelta(days=2000),
        )
        drivers.register_vehicle(
            driver,
            ride_type=RideType.objects.get(code=ride_type),
            make="Maruti Suzuki",
            model="Swift",
            registration_number=f"TN09AB{1000 + n}",
            year=2022,
            color="White",
            seats=4,
        )
        for doc_type in REQUIRED_DOCUMENTS:
            document = drivers.submit_document(
                driver,
                doc_type=doc_type,
                number_last4="1234",
                expires_on=date.today() + timedelta(days=400),
            )
            drivers.review_document(document, approve=True, reviewer=admin)
        driver.refresh_from_db()
        if online:
            lat, lng = at or (T_NAGAR[0] + 0.004, T_NAGAR[1] + 0.003)
            drivers.go_online(driver, lat=lat, lng=lng, now=now)
            driver.refresh_from_db()
        return driver

    return factory


@pytest.fixture
def api():
    def client_for(user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    return client_for


@pytest.fixture
def muted_notifications():
    with notifications.muted():
        yield
