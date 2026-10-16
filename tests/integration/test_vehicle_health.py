"""Vehicle health: condition (on the road, workshop, off the road), the daily check, faults
from drivers and riders, a breakdown mid-ride, and service records with parts and costs."""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.drivers.models import Vehicle, VehicleCondition
from apps.fleet import maintenance
from apps.fleet.models import IssueSource, IssueStatus, ServiceKind, VehicleIssue
from apps.rides import dispatch
from apps.rides.models import Trip, TripStatus
from apps.support.models import SupportTicket

from ..conftest import T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db

ALL_GOOD = dict.fromkeys(maintenance.CHECKLIST, True)


def test_failed_brakes_on_the_daily_check_ground_the_car_until_repaired(mini, make_driver, now):
    driver = make_driver(now=now)
    vehicle = Vehicle.objects.get(driver=driver)
    maintenance.submit_inspection(vehicle, driver=driver, items=ALL_GOOD, now=now)
    assert maintenance.health_of(vehicle, now=now)["checked_today"]

    with pytest.raises(BusinessRuleViolation, match="every item"):
        maintenance.submit_inspection(vehicle, driver=driver, items={"brakes": True}, now=now)
    maintenance.submit_inspection(
        vehicle, driver=driver, items={**ALL_GOOD, "brakes": False, "clean": False}, now=now
    )
    vehicle.refresh_from_db()
    assert vehicle.condition == VehicleCondition.OFF_ROAD
    health = maintenance.health_of(vehicle, now=now)
    assert health["state"] == "OFF_ROAD" and len(health["open_issues"]) == 2
    with pytest.raises(BusinessRuleViolation, match="off the road"):
        drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)
    with pytest.raises(BusinessRuleViolation, match="critical fault"):
        maintenance.set_condition(vehicle, VehicleCondition.ACTIVE)

    record = maintenance.record_service(
        vehicle,
        user=driver.user,
        kind=ServiceKind.REPAIR,
        workshop="Sri Murugan Motors",
        parts=[{"name": "Brake pads", "cost": "1800"}, {"name": "Brake fluid", "cost": "450.50"}],
        labour_cost="600",
        invoice_number="SMM/2026/118",
    )
    assert record.parts_cost == Decimal("2250.50") and record.total_cost == Decimal("2850.50")
    vehicle.refresh_from_db()
    assert vehicle.condition == VehicleCondition.ACTIVE  # every open fault fixed by the repair
    assert not VehicleIssue.objects.exclude(status=IssueStatus.RESOLVED).exists()
    assert maintenance.history(vehicle)[0]["fixed"]
    drivers.go_online(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now)


def test_breakdown_before_pickup_finds_another_driver(mini, make_driver, now):
    first, second = make_driver(now=now), make_driver(now=now)
    rider = make_rider()
    trip = book(rider, mini, now=now)
    offer = pending_offer(trip)
    trip = dispatch.accept_offer(offer, driver=offer.driver, now=now)
    broken = Vehicle.objects.get(driver=trip.driver)
    maintenance.report_issue(
        broken, user=trip.driver.user, source=IssueSource.DRIVER, kind="BREAKDOWN", now=now
    )
    trip.refresh_from_db()
    assert trip.status == TripStatus.REQUESTED and trip.driver is None  # back to dispatch
    assert {first.pk, second.pk} - {broken.driver_id}


def test_breakdown_mid_ride_costs_the_rider_nothing(mini, make_driver, now, admin):
    driver = make_driver(now=now)
    rider = make_rider()
    trip = book(rider, mini, now=now)
    offer = pending_offer(trip)
    trip = dispatch.accept_offer(offer, driver=driver, now=now)
    from apps.rides import services as rides

    drivers.update_location(driver, lat=trip.pickup_lat, lng=trip.pickup_lng, now=now)
    trip = rides.mark_arrived(trip, driver=driver, now=now)
    trip = rides.start_trip(trip, driver=driver, otp=trip.otp, now=now)
    maintenance.report_issue(
        Vehicle.objects.get(driver=driver),
        user=driver.user,
        source=IssueSource.DRIVER,
        kind="BREAKDOWN",
        description="Clutch gone",
        now=now,
    )
    trip.refresh_from_db()
    assert trip.status == TripStatus.CANCELLED and trip.cancellation_fee == 0
    assert SupportTicket.objects.filter(trip=trip, priority="HIGH").exists()


def test_rider_can_report_the_car_once_and_it_stays_on_the_road(api, mini, make_driver, now):
    driver = make_driver(now=now)
    rider = make_rider()
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    client = api(rider.user)
    url = f"/api/v1/trips/{trip.pk}/vehicle-issue/"
    assert client.post(url, {"kind": "BREAKDOWN"}, format="json").status_code == 400
    response = client.post(url, {"kind": "AC", "description": "AC not cooling"}, format="json")
    assert response.status_code == 201
    assert client.post(url, {"kind": "AC"}, format="json").status_code == 422  # once per ride
    vehicle = Vehicle.objects.get(driver=driver)
    assert vehicle.condition == VehicleCondition.ACTIVE  # a rider can't ground a car
    assert maintenance.health_of(vehicle)["state"] == "DUE"
    other = make_rider()
    assert api(other.user).post(url, {"kind": "AC"}, format="json").status_code in (403, 404)


def test_driver_api_check_and_costs(api, mini, make_driver, now):
    driver = make_driver(now=now)
    drive_to_completion(book(make_rider(), mini, now=now), now=now)
    client = api(driver.user)
    care = client.get("/api/v1/driver/biz/vehicle/").json()
    assert set(care["checklist"]) == set(maintenance.CHECKLIST) and not care["checked_today"]
    care = client.post(
        "/api/v1/driver/biz/vehicle/check/", {"items": ALL_GOOD}, format="json"
    ).json()
    assert care["checked_today"] and care["state"] == "OK"
    care = client.post(
        "/api/v1/driver/biz/vehicle/",
        {"kind": "TYRES", "parts": [{"name": "Tyre", "cost": "3200"}], "labour_cost": "200"},
        format="json",
    ).json()
    assert care["history"][0]["total_cost"] == "3400.00"
    assert care["costs"]["spend"] == "3400.00" and care["costs"]["km"] >= 0
    assert Trip.objects.filter(driver=driver).exists()
