"""Outstation extras: estimated tolls, an interstate permit when crossing a state border, and a
night driving allowance, all passed straight to the driver (no commission, no GST)."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.rides.packages import intercity_distance, intercity_fare

pytestmark = pytest.mark.django_db

CHENNAI = (13.05, 80.23)
VELLORE = (12.93, 79.14)  # Tamil Nadu
TIRUPATI = (13.63, 79.45)  # Andhra Pradesh


def _at(hour):
    day = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour))


def _codes(fare):
    return {line.code: line.amount for line in fare.lines}


def test_tolls_permit_and_night(chennai, mini):
    same_state = intercity_fare(
        chennai, mini, intercity_distance(CHENNAI, VELLORE), dropoff=VELLORE, depart_at=_at(9)
    )
    lines = _codes(same_state)
    assert lines["TOLLS"] > 0 and "PERMIT" not in lines and "NIGHT" not in lines

    other_state = intercity_fare(
        chennai, mini, intercity_distance(CHENNAI, TIRUPATI), dropoff=TIRUPATI, depart_at=_at(23)
    )
    lines = _codes(other_state)
    assert lines["PERMIT"] == Decimal(400) and lines["NIGHT"] == Decimal(250)
    extra = lines["TOLLS"] + lines["PERMIT"] + lines["NIGHT"] + lines["ALLOWANCE"]
    # All of it reaches the driver, none of it is taxed.
    assert other_state.total == other_state.taxable + other_state.gst + extra
    assert other_state.driver_earning == (
        other_state.ride_fare - other_state.platform_commission + extra
    )
