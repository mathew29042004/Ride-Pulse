"""The staff organisation (roles, permissions, org chart) and growing the network."""

from unittest import mock

import pytest

from apps.accounts.models import Role, StaffProfile
from apps.accounts.roles import Cap, capabilities_for
from apps.drivers.models import DriverProfile
from apps.geo.models import City
from apps.simulation import network

from ..conftest import make_staff

pytestmark = pytest.mark.django_db


def test_associate_managers_get_only_their_line_of_business():
    parcels = capabilities_for(Role.ASSOC_PARCELS)
    assert Cap.TRIPS_MANAGE in parcels and Cap.SUPPORT_MANAGE in parcels
    assert Cap.PRICING_MANAGE not in parcels and Cap.PAYOUTS_MANAGE not in parcels
    fleet = capabilities_for(Role.ASSOC_MAINTENANCE)
    assert Cap.DRIVERS_VERIFY in fleet and Cap.DRIVERS_MANAGE in fleet
    assert Cap.SUPPORT_MANAGE not in fleet
    intercity = capabilities_for(Role.ASSOC_INTERCITY)
    assert Cap.PRICING_MANAGE in intercity
    assert Cap.DRIVERS_VERIFY in capabilities_for(Role.FLEET_EXECUTIVE)
    assert Cap.TEAM_VIEW not in capabilities_for(Role.SUPPORT_AGENT)
    assert Cap.AUDIT_VIEW in capabilities_for(Role.REGIONAL_MANAGER)
    assert Cap.AUDIT_VIEW not in capabilities_for(Role.OPS_MANAGER)


def test_network_builder_creates_the_org_and_assigns_drivers(admin, make_driver):
    make_driver()  # an existing Chennai driver gets a fleet executive too
    targets = {"chennai": 3, "bengaluru": 3}
    with (
        mock.patch.object(network, "METROS", targets),
        mock.patch.object(network, "TIER_ONE", {}),
        mock.patch.object(network, "OTHER_CITY_DRIVERS", 1),
        mock.patch.object(network, "BOT_RIDERS_TARGET", 5),
        mock.patch.object(network, "MIN_PER_VEHICLE", 0),
    ):
        stats = network.NetworkBuilder(log=lambda *_: None).run()
        again = network.NetworkBuilder(log=lambda *_: None).run()  # idempotent top-up

    cities = City.objects.count()
    assert DriverProfile.objects.filter(city__slug="madurai").count() == 1
    assert stats["staff:REGIONAL_MANAGER"] == 4
    assert stats["staff:OPS_MANAGER"] == cities  # one manager per city
    assert stats["staff:ASSOC_PARCELS"] == 4  # one per state
    assert "drivers_added" not in again and again["employees"] == stats["employees"]
    assert not DriverProfile.objects.filter(fleet_executive__isnull=True).exists()

    # Reporting lines: fleet executive → city manager → regional manager → head.
    executive = StaffProfile.objects.filter(
        user__role=Role.FLEET_EXECUTIVE, city__slug="kochi"
    ).first()
    manager = executive.reports_to
    assert manager.user.role == Role.OPS_MANAGER and manager.city.slug == "kochi"
    assert manager.reports_to.user.role == Role.REGIONAL_MANAGER
    assert manager.reports_to.state == "Kerala"
    assert manager.reports_to.reports_to.user == admin
    # Demo logins exist for the new roles.
    assert StaffProfile.objects.filter(
        user__email="parcels@ridepulse.dev", state="Tamil Nadu"
    ).exists()


def test_team_api(api, admin):
    with (
        mock.patch.object(network, "METROS", {}),
        mock.patch.object(network, "TIER_ONE", {}),
        mock.patch.object(network, "OTHER_CITY_DRIVERS", 0),
        mock.patch.object(network, "BOT_RIDERS_TARGET", 0),
        mock.patch.object(network, "MIN_PER_VEHICLE", 0),
    ):
        network.NetworkBuilder(log=lambda *_: None).run()
    client = api(admin)
    tree = client.get("/api/v1/team/tree/").json()
    assert len(tree) == 1 and tree[0]["role"] == "ADMIN"
    regions = {r["state"] for r in tree[0]["reports"]}
    assert regions == {"Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh"}
    kerala = client.get("/api/v1/team/tree/?state=Kerala").json()
    assert {r["state"] for r in kerala[0]["reports"]} == {"Kerala"}
    summary = client.get("/api/v1/team/summary/").json()
    assert summary["employees"] == StaffProfile.objects.count()
    associates = client.get("/api/v1/team/?department=PARCELS").json()["results"]
    assert {a["role"] for a in associates} == {"ASSOC_PARCELS"}

    assert api(make_staff(Role.SUPPORT_AGENT)).get("/api/v1/team/").status_code == 403
    assert api(make_staff(Role.ASSOC_RIDES)).get("/api/v1/team/tree/").status_code == 200
    me = client.get("/api/v1/auth/me/").json()
    assert me["role_label"] == "Administrator"
