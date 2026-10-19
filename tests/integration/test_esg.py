"""Company CO₂ report: business trips only, emissions and savings, CSV, managers only."""

from decimal import Decimal

import pytest

from apps.riders import esg, profiles

from ..conftest import make_rider
from .helpers import drive_to_completion

pytestmark = pytest.mark.django_db


def test_report_and_csv(api, mini, make_driver, now):
    from apps.payments import services as payments
    from apps.rides import services as rides

    from ..conftest import MARINA, T_NAGAR

    owner = make_rider(first_name="Owner")
    payments.top_up(owner.user, Decimal(2000), method="UPI", payer_reference="o@upi")
    company = profiles.create_profile(owner, kind="BUSINESS", name="Acme Pvt Ltd")
    make_driver(now=now)
    trip = rides.request_trip(
        rider=owner,
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        payment_profile=company,
        trip_purpose="Client visit",
        now=now,
    )
    drive_to_completion(trip, now=now)
    r = esg.report(company, month=f"{now:%Y-%m}")
    assert r["trips"] == 1 and r["co2_kg"] > 0 and r["saved_kg"] > 0 and len(r["trend"]) == 6
    body, name = esg.csv_export(company, month=f"{now:%Y-%m}")
    assert body.decode().startswith("trip,date,employee") and name.endswith(".csv")
    assert api(owner.user).get(f"/api/v1/rider/business/{company.pk}/co2/").status_code == 200
    stranger = make_rider(first_name="Stranger")
    assert api(stranger.user).get(f"/api/v1/rider/business/{company.pk}/co2/").status_code == 403
