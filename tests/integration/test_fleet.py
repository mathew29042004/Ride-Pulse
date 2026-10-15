"""Driver business: statements and TDS, fleet owners, vehicle upkeep, EVs, quests and the
airport queue."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.dates import week_start
from apps.core.exceptions import BusinessRuleViolation, ConflictError
from apps.drivers import services as drivers
from apps.drivers.models import DocumentType, FuelType, Vehicle
from apps.fleet import airport, ev, maintenance, owners, quests, statements
from apps.fleet.models import AirportQueueEntry, ChargingStation, DriverStatement, QueueStatus
from apps.geo.models import Zone
from apps.payments import accounts
from apps.payments import services as payments
from apps.rides import dispatch
from apps.rides.models import Trip

from ..conftest import T_NAGAR, make_rider, make_staff
from .helpers import book, drive_to_completion, money, pending_offer

pytestmark = pytest.mark.django_db


def last_week_trip(mini, driver, now):
    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    monday = week_start(timezone.localdate(now)) - timedelta(days=7)
    when = timezone.make_aware(timezone.datetime.combine(monday, timezone.datetime.min.time()))
    Trip.objects.filter(pk=trip.pk).update(completed_at=when + timedelta(hours=10))
    trip.refresh_from_db()
    return trip, monday


# --- Statements and TDS ----------------------------------------------------------------------


def test_weekly_statement_withholds_tds(mini, make_driver, now):
    driver = make_driver(now=now)
    trip, monday = last_week_trip(mini, driver, now)
    before = payments.wallet_balance(driver.user)
    assert statements.generate_week(monday, now=now) == 1
    st = DriverStatement.objects.get(driver=driver)
    assert not st.pan_on_file and st.tds_rate == Decimal("0.05")  # no PAN: 5%
    assert st.tds_amount == money(trip.fare_total * Decimal("0.05"))
    assert st.trips == 1 and st.gross_fares == trip.fare_total
    assert payments.wallet_balance(driver.user) == before - st.tds_amount
    assert payments.account_balances()[accounts.TDS_PAYABLE] == st.tds_amount
    assert statements.generate_week(monday, now=now) == 0  # once a week
    assert statements.render_pdf(st).startswith(b"%PDF")
    assert payments.verify_ledger()["balanced"]


def test_pan_cuts_tds_to_a_tenth_of_a_percent(mini, make_driver, now, admin):
    driver = make_driver(now=now)
    doc = drivers.submit_document(
        driver, doc_type=DocumentType.PAN, number_last4="123F", expires_on=None
    )
    drivers.review_document(doc, approve=True, reviewer=admin)
    _, monday = last_week_trip(mini, driver, now)
    statements.generate_week(monday, now=now)
    assert DriverStatement.objects.get(driver=driver).tds_rate == Decimal("0.001")
    fy, quarter = statements.current_quarter(monday)
    report = statements.tds_report(fy, quarter)
    assert report["drivers"] == 1 and report["without_pan"] == 0


# --- Fleet owners ----------------------------------------------------------------------------


def make_owner(chennai, share=Decimal("20")):
    return owners.create_owner(
        email="owner@test.dev",
        first_name="Ravi",
        last_name="Kumar",
        phone="9800000001",
        company_name="Ravi Travels",
        city=chennai,
        share_percent=share,
    )


def test_fleet_owner_gets_their_share_and_a_payout(chennai, mini, make_driver, now, settings):
    owner = make_owner(chennai)
    driver = make_driver(now=now)
    owners.add_driver(owner, driver, now=now)
    assert Vehicle.objects.get(driver=driver).owner == owner
    with pytest.raises(ConflictError):
        owners.add_driver(
            owners.create_owner(
                email="b@test.dev",
                first_name="B",
                last_name="",
                phone="9800000002",
                company_name="B Cabs",
                city=chennai,
            ),
            driver,
        )

    trip = drive_to_completion(book(make_rider(), mini, now=now), now=now)
    share = owners.owner_share(trip, Decimal("20"))
    assert share > 0
    assert payments.wallet_balance(owner.user) == share
    board = owners.dashboard(owner, now=now + timedelta(hours=1))
    assert board["drivers"][0]["week_trips"] == 1 and board["balance"] == str(share)
    assert payments.verify_ledger()["balanced"]

    # The weekly run pays owners too, once their balance passes the minimum.
    settings.RIDE_PULSE = {**settings.RIDE_PULSE, "PAYOUT_MINIMUM": "1"}
    payouts = payments.create_weekly_payouts(now=now)
    owner_payout = next(p for p in payouts if p.fleet_owner_id == owner.pk)
    assert owner_payout.amount == share and owner_payout.payee == owner.user
    assert payments.wallet_balance(owner.user) == 0


def test_owner_portal_api_is_private(api, chennai, mini, make_driver, now):
    owner = make_owner(chennai)
    client = api(owner.user)
    assert client.get("/api/v1/fleet/dashboard/").json()["company"] == "Ravi Travels"
    assert client.get("/api/v1/trips/").status_code == 403  # an owner isn't staff
    assert client.get("/api/v1/ops/fleet/owners/").status_code == 403
    fleet_exec = api(make_staff(Role.FLEET_EXECUTIVE))
    assert fleet_exec.get("/api/v1/ops/fleet/owners/").json()[0]["company_name"] == "Ravi Travels"


# --- Vehicle upkeep --------------------------------------------------------------------------


def test_service_due_and_expired_insurance(mini, make_driver, now):
    driver = make_driver(now=now)
    vehicle = Vehicle.objects.get(driver=driver)
    Vehicle.objects.filter(pk=vehicle.pk).update(
        odometer_base_km=9_700, permit_expires_on=date.today() + timedelta(days=10)
    )
    vehicle.refresh_from_db()
    health = maintenance.vehicle_health(vehicle)
    assert health["service"] == "DUE_SOON" and health["service_due_in_km"] == 300
    assert health["documents"][0]["status"] == "EXPIRING"
    assert maintenance.sweep(now=now)["warned"] == 1
    assert maintenance.sweep(now=now)["warned"] == 0  # once a week

    maintenance.record_service(vehicle, user=driver.user, workshop="Maruti Arena")
    vehicle.refresh_from_db()
    assert maintenance.vehicle_health(vehicle)["service"] == "OK"
    with pytest.raises(BusinessRuleViolation, match="below the last service"):
        maintenance.record_service(vehicle, user=driver.user, odometer_km=100)

    Vehicle.objects.filter(pk=vehicle.pk).update(
        insurance_expires_on=date.today() - timedelta(days=1)
    )
    drivers.go_offline(driver)
    with pytest.raises(BusinessRuleViolation, match="insurance expired"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1])


# --- EVs -------------------------------------------------------------------------------------


def test_ev_range_limits_dispatch_and_drains(chennai, mini, make_driver, now):
    driver = make_driver(now=now)
    Vehicle.objects.filter(driver=driver).update(fuel_type=FuelType.EV, battery_percent=8)
    driver.refresh_from_db()
    trip = book(make_rider(), mini, now=now)  # ~6 km: 8% of 250 km = 20 km, minus 15 reserve
    assert pending_offer(trip) is None
    ev.set_battery(driver, 80, now=now)
    dispatch.dispatch_trip(trip, now=now)
    assert pending_offer(trip).driver == driver
    drive_to_completion(trip, now=now)
    vehicle = Vehicle.objects.get(driver=driver)
    assert vehicle.battery_percent < 80

    ChargingStation.objects.create(
        city=chennai,
        name="Statiq · T. Nagar",
        operator="Statiq",
        lat=13.04,
        lng=80.235,
        power_kw=60,
        connectors=4,
        price_per_kwh=Decimal("18"),
    )
    ev.set_battery(driver, 15, now=now)
    info = ev.my_ev(driver)
    assert info["low"] and info["chargers"][0]["name"] == "Statiq · T. Nagar"
    assert driver.user.notifications.filter(title__startswith="Battery at 15%").exists()


# --- Quests ----------------------------------------------------------------------------------


def test_quest_pays_tiers_within_budget(chennai, mini, make_driver, now, admin):
    driver = make_driver(now=now)
    quest = quests.create_quest(
        user=admin,
        name="Weekend warrior",
        city=chennai,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        tiers=[[1, 50], [2, 120]],
        budget=Decimal("170"),
        now=now,
    )
    assert driver.user.notifications.filter(title="New quest: Weekend warrior").exists()
    before = payments.wallet_balance(driver.user)
    for i in range(2):
        start = now + timedelta(hours=i)
        drivers.update_location(driver, lat=13.0448, lng=80.2371, now=start)
        drive_to_completion(book(make_rider(), mini, now=start), now=start)
    quest.refresh_from_db()
    assert quest.spent == Decimal("120")  # 50, then 70 more at the second tier
    assert quests.for_driver(driver, now=now)[0]["trips"] == 2
    assert payments.wallet_balance(driver.user) > before
    assert payments.verify_ledger()["balanced"]
    with pytest.raises(BusinessRuleViolation, match="more trips and a bigger reward"):
        quests.create_quest(
            user=admin,
            name="Bad",
            city=chennai,
            starts_at=now,
            ends_at=now + timedelta(days=1),
            tiers=[[5, 100], [3, 200]],
            budget=Decimal("500"),
            now=now,
        )


# --- Airport queue ---------------------------------------------------------------------------


def test_airport_queue_order_and_dispatch(chennai, mini, make_driver, now):
    zone = Zone.objects.get(city=chennai, is_airport=True)
    at_airport = (zone.center_lat, zone.center_lng)
    first = make_driver(at=at_airport, now=now)
    second = make_driver(
        at=(zone.center_lat + 0.001, zone.center_lng), now=now + timedelta(seconds=5)
    )
    passing = make_driver(at=(zone.center_lat + 0.002, zone.center_lng + 0.001), now=now)
    AirportQueueEntry.objects.filter(driver=passing).delete()  # just passing through
    assert airport.my_spot(first)["position"] == 1 and airport.my_spot(second)["position"] == 2

    trip = book(make_rider(), mini, now=now, pickup=at_airport, dropoff=T_NAGAR)
    assert pending_offer(trip).driver == first  # first in line, not the nearest
    dispatch.accept_offer(pending_offer(trip), driver=first, now=now)
    assert AirportQueueEntry.objects.get(driver=first).status == QueueStatus.DISPATCHED
    assert airport.my_spot(second)["position"] == 1

    # Leaving the airport for longer than the grace period drops you out of the line.
    drivers.update_location(second, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now + timedelta(minutes=1))
    drivers.update_location(second, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now + timedelta(minutes=8))
    assert airport.my_spot(second) is None
    row = next(
        r for r in airport.overview(now=now + timedelta(minutes=9)) if r["zone_id"] == zone.pk
    )
    assert row["served_24h"] == 1
