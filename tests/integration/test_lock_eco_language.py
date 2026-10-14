"""Fare Lock, Eco score and the Language Bridge."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.drivers import services as drivers
from apps.drivers.models import DriverSession, Vehicle
from apps.payments.services import verify_ledger, wallet_balance
from apps.pricing import fare_locks
from apps.pricing.models import SurgeOverride
from apps.rides import dispatch, eco, translate
from apps.rides import services as rides

from ..conftest import MARINA, T_NAGAR, make_rider
from .helpers import book, drive_to_completion, pending_offer

pytestmark = pytest.mark.django_db


def test_fare_lock_beats_surge(rider, mini, make_driver, now, chennai):
    make_driver(now=now)
    first = drive_to_completion(book(rider, mini, now=now), now=now)
    lock = fare_locks.lock_from_trip(
        first, user=rider.user, method="UPI", weekdays=list(range(7)), now=now
    )
    assert lock.fee == Decimal(49) and lock.locked_total > 0 and lock.weekdays == list(range(7))

    # Surge doubles prices; the locked commute still costs the locked fare.
    zone = first.pickup_zone
    SurgeOverride.objects.create(
        zone=zone,
        multiplier=Decimal(2),
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        reason="test",
    ) if zone else None
    later = now + timedelta(days=1)
    # A new day: the driver comes back online fresh (otherwise Wellbeing sends them to rest).
    DriverSession.objects.filter(driver=first.driver).delete()
    DriverSession.objects.create(driver=first.driver, started_at=later)
    drivers.update_location(first.driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=later)
    options = rides.estimate_options(rider=rider, pickup=T_NAGAR, dropoff=MARINA, at=later)
    mini_option = next(o for o in options["options"] if o["ride_type"] == mini)
    assert mini_option["fare_lock"] is True
    assert mini_option["estimate"].fare.total <= lock.locked_total
    other = next(o for o in options["options"] if o["ride_type"].code == "SEDAN")
    assert other["fare_lock"] is False  # only the locked ride type

    trip = book(rider, mini, now=later)
    assert trip.fare_lock_id == lock.pk and trip.estimated_fare <= lock.locked_total
    trip = drive_to_completion(trip, now=later)
    assert trip.fare_total <= lock.locked_total
    assert trip.driver_earning > 0  # the driver isn't the one paying for the lock
    assert verify_ledger()["balanced"]

    # A different time of day doesn't match.
    away = timezone.localtime(later) + timedelta(hours=5)
    assert fare_locks.matching_lock(rider, mini, T_NAGAR, MARINA, away) is None


def test_fare_lock_needs_a_completed_ride(rider, mini, make_driver, now):
    make_driver(now=now)
    trip = book(rider, mini, now=now)
    with pytest.raises(Exception, match="completed ride"):
        fare_locks.lock_from_trip(trip, user=rider.user, method="WALLET", now=now)


def test_eco_points_and_redeem(rider, mini, make_driver, now):
    driver = make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    # A petrol Mini saves 50 g/km against driving your own car.
    assert trip.co2_saved_g == int(50 * float(trip.estimated_distance_km))
    rider.refresh_from_db()
    assert rider.eco_points == trip.co2_saved_g // 100

    Vehicle.objects.filter(driver=driver).update(fuel_type="EV")
    drivers.update_location(driver, lat=T_NAGAR[0], lng=T_NAGAR[1], now=now + timedelta(hours=1))
    trip = drive_to_completion(
        book(rider, mini, now=now + timedelta(hours=1)), now=now + timedelta(hours=1)
    )
    assert trip.co2_saved_g == int(150 * float(trip.estimated_distance_km))

    with pytest.raises(BusinessRuleViolation):
        type(rider).objects.filter(pk=rider.pk).update(eco_points=50)
        eco.redeem(rider)
    type(rider).objects.filter(pk=rider.pk).update(eco_points=250)
    before = wallet_balance(rider.user)
    result = eco.redeem(rider)
    assert wallet_balance(rider.user) == before + Decimal(20) and result["points"] == 50
    assert verify_ledger()["balanced"]


def test_electric_preference_puts_evs_first(mini, make_driver, now):
    petrol = make_driver(now=now)
    ev = make_driver(now=now)
    Vehicle.objects.filter(driver=ev).update(fuel_type="EV")
    trip = book(make_rider(), mini, now=now, preferences=["ELECTRIC"])
    assert pending_offer(trip).driver == ev
    assert petrol != ev


def test_phrasebook_translates_quick_replies():
    language, out = translate.translate("I'm on my way", sender_language="en", target="ta")
    assert language == "en" and out["ta"] == "வந்துகொண்டிருக்கிறேன்" and "hi" in out
    language, out = translate.translate("சரி 👍", sender_language="ta", target="en")
    assert language == "ta" and out["en"] == "Okay 👍"
    # Free text needs the Google key; without it, no translation (the original is shown).
    assert translate.translate(
        "Gate number 4 near the bakery", sender_language="en", target="hi"
    ) == ("en", {})
    with mock.patch.object(translate, "_google", return_value="बेकरी के पास गेट 4"):
        _, out = translate.translate(
            "Gate number 4 near the bakery", sender_language="en", target="hi"
        )
    assert out == {"hi": "बेकरी के पास गेट 4"}


def test_chat_messages_carry_translations(api, rider, mini, make_driver, now):
    driver = make_driver(now=now)
    driver.user.language = "ta"
    driver.user.save()
    trip = book(rider, mini, now=now)
    trip = dispatch.accept_offer(pending_offer(trip), driver=driver, now=now)
    message = rides.send_message(trip, user=rider.user, body="Please come to the main gate")
    assert message.language == "en"
    assert message.translations["ta"] == "தயவுசெய்து பிரதான வாயிலுக்கு வாருங்கள்"
    seen = api(driver.user).get(f"/api/v1/trips/{trip.pk}/messages/").json()
    assert seen[0]["translations"]["ta"].startswith("தயவுசெய்து")
    assert api(rider.user).patch("/api/v1/auth/me/", {"language": "hi"}).json()["language"] == "hi"


def test_api(api, rider, mini, make_driver, now):
    make_driver(now=now)
    trip = drive_to_completion(book(rider, mini, now=now), now=now)
    client = api(rider.user)
    locked = client.post(f"/api/v1/trips/{trip.pk}/lock-fare/", {"method": "UPI"}, format="json")
    assert locked.status_code == 201 and locked.json()["weekdays"] == [0, 1, 2, 3, 4]
    assert (
        client.get("/api/v1/rider/fare-locks/").json()[0]["reference"] == locked.json()["reference"]
    )
    summary = client.get("/api/v1/rider/eco/").json()
    assert summary["co2_saved_kg_total"] >= 0 and summary["redeem_points"] == 100
