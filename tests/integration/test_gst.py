"""GST: an INV-01 e-invoice for business trips (missing billing details flagged), GSTR-1 data
with business invoices by GSTIN and consumer sales by state, CGST + SGST adding up."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.payments import gst
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider, make_staff
from .helpers import book, drive_to_completion
from .test_product import company, midday

pytestmark = pytest.mark.django_db


def test_business_e_invoice_and_gstr1(api, mini, make_driver, now):
    now = midday(now)
    owner, employee, profile = company(now)
    make_driver(now=now)
    trip = rides.request_trip(
        rider=employee,
        ride_type=mini,
        pickup=T_NAGAR,
        dropoff=MARINA,
        payment_method="UPI",
        payment_profile=profile,
        trip_purpose="Client visit",
        now=now,
    )
    trip = drive_to_completion(trip, now=now)
    draft = gst.e_invoice(trip)
    assert not draft["ready_to_upload"] and "buyer PIN" in draft["missing"]
    profile.billing_address, profile.billing_pin = "Tidel Park, Taramani", "600113"
    profile.save()
    trip.refresh_from_db()
    invoice = gst.e_invoice(trip)
    assert invoice["ready_to_upload"]
    body = invoice["invoice"]
    item, totals = body["ItemList"][0], body["ValDtls"]
    assert item["HsnCd"] == "996412" and body["BuyerDtls"]["Gstin"] == "33ABCDE1234F1Z5"
    assert Decimal(str(totals["CgstVal"])) + Decimal(str(totals["SgstVal"])) == Decimal(
        str(trip.final_fare.gst)
    )
    assert totals["IgstVal"] == 0

    make_driver(now=now)
    drive_to_completion(book(make_rider(), mini, now=now), now=now)  # a consumer ride
    data = gst.gstr1(timezone.localdate().replace(day=1))
    assert [r["buyer_gstin"] for r in data["b2b"]] == ["33ABCDE1234F1Z5"]
    tamil_nadu = next(r for r in data["b2cs"] if r["place_of_supply"] == "33-Tamil Nadu")
    assert tamil_nadu["rides"] == 1

    assert api(owner.user).get(f"/api/v1/gst/e-invoice/{trip.pk}/").status_code == 200
    assert api(make_rider().user).get(f"/api/v1/gst/e-invoice/{trip.pk}/").status_code == 403
    finance = api(make_staff(Role.OPS_MANAGER))
    csv = finance.get("/api/v1/gst/returns/?export=csv")
    assert csv.status_code == 200 and b"B2B" in csv.content and b"B2CS" in csv.content
