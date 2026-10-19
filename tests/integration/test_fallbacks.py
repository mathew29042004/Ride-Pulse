"""Fallback modes follow open incidents: payments down → cash only; maps down → no maps calls."""

from decimal import Decimal
from unittest import mock

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.reliability import fallbacks, incidents

from .helpers import book

pytestmark = pytest.mark.django_db


def test_payments_incident_means_cash_only(rider, mini, make_driver, ops, now, api):
    make_driver(now=now)
    incident = incidents.open_incident(
        user=ops,
        title="UPI failing",
        severity="MAJOR",
        components=["PAYMENTS"],
        public_message="UPI is down; pay in cash.",
        now=now,
    )
    assert fallbacks.CASH_ONLY in fallbacks.active()
    with pytest.raises(BusinessRuleViolation, match="Online payments are down"):
        book(rider, mini, now=now, method="UPI")
    assert book(rider, mini, now=now, method="CASH").payment_method == "CASH"
    assert api(rider.user).get("/api/v1/status/banner/").json()["fallbacks"] == ["cash_only"]
    incidents.update(incident, user=ops, status="RESOLVED", message="UPI is back.")
    assert fallbacks.active() == set()


def test_maps_incident_skips_the_maps_provider(ops, now):
    from apps.geo import routing

    incidents.open_incident(
        user=ops,
        title="Maps API errors",
        severity="MINOR",
        components=["MAPS"],
        public_message="ETAs may be less accurate.",
        now=now,
    )
    with (
        mock.patch("apps.geo.google.enabled", return_value=True),
        mock.patch("apps.geo.google.compute_route") as call,
    ):
        route = routing.estimate_route(13.04, 80.23, 13.05, 80.28, now)
    call.assert_not_called()
    assert route.source == "estimate" and route.distance_km > Decimal(0)
