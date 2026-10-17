"""GST e-invoices (the government's INV-01 JSON) for business trips, and the monthly GSTR-1
return data (business invoices by GSTIN; consumer sales summarised by state).

What this doesn't do: get an IRN. A real e-invoice is registered with the government's Invoice
Registration Portal through a GST Suvidha Provider, which needs a registered GST account (an
outside account, like Maps). The JSON here is what you'd upload.

Assumptions to confirm with a chartered accountant:
* SAC 996412 (passenger transport by taxi); GST at the configured rate (5% for ride-hailing,
  paid by the aggregator under section 9(5)).
* Place of supply is the state where the ride starts, and Ride Pulse is registered in each state
  it operates in, so every invoice is intra-state: CGST + SGST, half each.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.conf import company_address, company_gstin, company_name, gst_rate
from apps.core.exceptions import BusinessRuleViolation

SAC = "996412"
STATE_CODES = {"Tamil Nadu": "33", "Karnataka": "29", "Kerala": "32", "Andhra Pradesh": "37"}
CENT = Decimal("0.01")


def _split(tax: Decimal) -> tuple[Decimal, Decimal]:
    half = (tax / 2).quantize(CENT)
    return half, tax - half


def _amounts(trip) -> tuple[Decimal, Decimal]:
    fare = trip.final_fare
    return Decimal(fare.taxable).quantize(CENT), Decimal(fare.gst).quantize(CENT)


def _paid_trips(start, end):
    from apps.rides.models import Trip, TripPaymentStatus, TripStatus

    return Trip.objects.filter(
        status=TripStatus.COMPLETED,
        payment_status=TripPaymentStatus.PAID,
        completed_at__gte=start,
        completed_at__lt=end,
    ).select_related("city", "payment_profile")


def e_invoice(trip) -> dict:
    """The INV-01 JSON for a business trip (paid by a company profile with a GSTIN)."""
    from apps.rides.invoices import ensure_number

    profile = trip.payment_profile
    if profile is None or not profile.gstin:
        raise BusinessRuleViolation("E-invoices are for trips paid by a business with a GSTIN.")
    state = STATE_CODES.get(trip.city.state, "33")
    taxable, tax = _amounts(trip)
    cgst, sgst = _split(tax)
    number = ensure_number(trip)
    missing = [
        label
        for label, value in (
            ("buyer billing address", profile.billing_address),
            ("buyer PIN", profile.billing_pin),
        )
        if not value
    ]
    issued = timezone.localtime(trip.completed_at)
    seller_gstin = state + company_gstin()[2:]  # the registration in the state of supply
    return {
        "ready_to_upload": not missing,
        "missing": missing,
        "invoice": {
            "Version": "1.1",
            "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N"},
            "DocDtls": {"Typ": "INV", "No": number, "Dt": issued.strftime("%d/%m/%Y")},
            "SellerDtls": {
                "Gstin": seller_gstin,
                "LglNm": company_name(),
                "Addr1": company_address()[:100],
                "Loc": trip.city.name,
                "Stcd": state,
            },
            "BuyerDtls": {
                "Gstin": profile.gstin,
                "LglNm": profile.name,
                "Pos": state,
                "Addr1": profile.billing_address[:100],
                "Pin": profile.billing_pin,
                "Stcd": profile.gstin[:2],
            },
            "ItemList": [
                {
                    "SlNo": "1",
                    "PrdDesc": f"{trip.ride_type.name} ride {trip.trip_number}",
                    "IsServc": "Y",
                    "HsnCd": SAC,
                    "Qty": 1,
                    "Unit": "OTH",
                    "UnitPrice": float(taxable),
                    "TotAmt": float(taxable),
                    "AssAmt": float(taxable),
                    "GstRt": float(gst_rate() * 100),
                    "CgstAmt": float(cgst),
                    "SgstAmt": float(sgst),
                    "IgstAmt": 0,
                    "TotItemVal": float(taxable + tax),
                }
            ],
            "ValDtls": {
                "AssVal": float(taxable),
                "CgstVal": float(cgst),
                "SgstVal": float(sgst),
                "IgstVal": 0,
                "TotInvVal": float(taxable + tax),
            },
        },
    }


def gstr1(month: date) -> dict:
    """GSTR-1 data for a month: B2B invoices (by buyer GSTIN) and B2CS totals (by state)."""
    from apps.analytics.pnl import month_bounds

    start, end = month_bounds(month)
    b2b, b2cs = [], {}
    rate = float(gst_rate() * 100)
    for trip in _paid_trips(start, end).filter(Q(fare_total__gt=0)):
        try:
            taxable, tax = _amounts(trip)
        except Exception:
            continue
        state = trip.city.state
        if trip.payment_profile_id and trip.payment_profile.gstin:
            cgst, sgst = _split(tax)
            b2b.append(
                {
                    "trip_id": trip.pk,
                    "buyer_gstin": trip.payment_profile.gstin,
                    "buyer": trip.payment_profile.name,
                    "invoice": trip.invoice_number or trip.trip_number,
                    "date": timezone.localtime(trip.completed_at).date().isoformat(),
                    "place_of_supply": f"{STATE_CODES.get(state, '33')}-{state}",
                    "taxable": str(taxable),
                    "rate": rate,
                    "cgst": str(cgst),
                    "sgst": str(sgst),
                }
            )
        else:
            row = b2cs.setdefault(state, {"taxable": Decimal(0), "tax": Decimal(0), "invoices": 0})
            row["taxable"] += taxable
            row["tax"] += tax
            row["invoices"] += 1
    consumer = []
    for state, row in sorted(b2cs.items()):
        cgst, sgst = _split(row["tax"])
        consumer.append(
            {
                "place_of_supply": f"{STATE_CODES.get(state, '33')}-{state}",
                "rate": rate,
                "rides": row["invoices"],
                "taxable": str(row["taxable"].quantize(CENT)),
                "cgst": str(cgst),
                "sgst": str(sgst),
            }
        )
    total_taxable = sum((Decimal(r["taxable"]) for r in b2b + consumer), Decimal(0))
    total_tax = sum((Decimal(r["cgst"]) + Decimal(r["sgst"]) for r in b2b + consumer), Decimal(0))
    return {
        "month": start.date().isoformat()[:7],
        "sac": SAC,
        "b2b": b2b,
        "b2cs": consumer,
        "totals": {"taxable": str(total_taxable), "tax": str(total_tax), "b2b_invoices": len(b2b)},
        "note": "Data for GSTR-1. Confirm the SAC code and the place-of-supply treatment with a "
        "chartered accountant before filing.",
    }
