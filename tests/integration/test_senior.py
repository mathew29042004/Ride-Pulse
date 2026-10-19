"""Senior citizen mode: assist-trained, top-rated drivers first; family follows every ride."""

from decimal import Decimal
from unittest import mock

import pytest

from apps.drivers.models import DriverProfile
from apps.riders.models import TrustedContact
from apps.rides import safety
from apps.rides.models import RidePreference

from .helpers import book, pending_offer

pytestmark = pytest.mark.django_db


def test_senior_gets_assist_trained_driver_and_family_follows(rider, mini, make_driver, now):
    near = make_driver(now=now)
    trained = make_driver(now=now, at=(13.0470, 80.2390))
    DriverProfile.objects.filter(pk=trained.pk).update(assist_trained=True, rating=Decimal("4.9"))
    rider.accessibility = [RidePreference.SENIOR]
    rider.save(update_fields=["accessibility"])
    TrustedContact.objects.create(rider=rider, name="Son", phone="9876543210", share_mode="NEVER")
    trip = book(rider, mini, now=now)
    assert RidePreference.SENIOR in trip.preferences
    assert pending_offer(trip).driver == trained and near
    with mock.patch("apps.accounts.sms.send_text"):
        assert list(safety.contacts_for(trip))  # shared even though the contact's mode is "never"
