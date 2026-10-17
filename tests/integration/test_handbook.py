"""The staff handbook: staff see the internal procedures (by category, for tickets); riders and
drivers can neither list nor open them, even with the link."""

import pytest

from apps.accounts.models import Role

from ..conftest import make_rider, make_staff

pytestmark = pytest.mark.django_db


def test_staff_read_procedures_and_riders_cannot(api, make_driver, now):
    staff = api(make_staff(Role.SUPPORT_AGENT))
    safety = staff.get("/api/v1/help/?category=Safety").json()
    assert {a["slug"] for a in safety} >= {"sop-sos", "sop-ride-check"}
    assert staff.get("/api/v1/help/sop-sos/").status_code == 200
    rider = api(make_rider().user)
    assert all(not a["slug"].startswith("sop-") for a in rider.get("/api/v1/help/?q=refund").json())
    assert rider.get("/api/v1/help/sop-sos/").status_code == 404
    driver = api(make_driver(now=now).user)
    assert driver.get("/api/v1/help/sop-fraud/").status_code == 404
