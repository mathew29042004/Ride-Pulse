"""Incentive quests: "20 trips this weekend = ₹500", created by ops without code changes.

* A quest has a city (or a whole state), ride types, a time window, reward tiers
  (e.g. 10 trips = ₹150, 20 trips = ₹400 in total), optional peak-hours-only and minimum rating
  rules, and a budget.
* Live quests count each qualifying completed trip; reaching a tier pays the difference
  straight into the driver's wallet (an INCENTIVE posting from ``platform:promotions``).
* The budget is a hard cap: once a reward would overrun it, payouts stop and ops are told.
"""

from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify, notify_role
from apps.payments import accounts
from apps.payments.models import TransactionKind
from apps.payments.services import ensure_wallet, post

from .models import Quest, QuestProgress, QuestStatus

PEAK_HOURS = (range(7, 10), range(17, 21))


def _clean_tiers(tiers) -> list[list]:
    try:
        clean = [[int(t), str(Decimal(str(r)))] for t, r in tiers]
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise BusinessRuleViolation("Tiers are [trips, reward] pairs.", field="tiers") from exc
    if not clean or len(clean) > 5:
        raise BusinessRuleViolation("Give 1-5 reward tiers.", field="tiers")
    for (t1, r1), (t2, r2) in pairwise(clean):
        if t2 <= t1 or Decimal(r2) <= Decimal(r1):
            raise BusinessRuleViolation(
                "Each tier needs more trips and a bigger reward than the one before.", field="tiers"
            )
    if clean[0][0] < 1 or Decimal(clean[0][1]) <= 0:
        raise BusinessRuleViolation("Tiers need at least 1 trip and a reward.", field="tiers")
    return clean


@transaction.atomic
def create_quest(
    *,
    user,
    name: str,
    starts_at: datetime,
    ends_at: datetime,
    tiers,
    budget: Decimal,
    city=None,
    state: str = "",
    ride_types=(),
    peak_hours_only: bool = False,
    min_rating: Decimal | None = None,
    launch: bool = True,
    now: datetime | None = None,
) -> Quest:
    now = now or timezone.now()
    if ends_at <= starts_at or ends_at <= now:
        raise BusinessRuleViolation("The quest must end after it starts, in the future.")
    if (ends_at - starts_at).days > 31:
        raise BusinessRuleViolation("Quests run for at most a month.", field="ends_at")
    if not city and not state:
        raise BusinessRuleViolation("Choose a city or a state.", field="city")
    tiers = _clean_tiers(tiers)
    if Decimal(budget) < Decimal(tiers[-1][1]):
        raise BusinessRuleViolation(
            "The budget must cover at least one top reward.", field="budget"
        )
    quest = Quest.objects.create(
        number=next_reference("QST", year=timezone.localtime(now).year),
        name=" ".join(name.split())[:120],
        city=city,
        state=state if not city else city.state,
        starts_at=starts_at,
        ends_at=ends_at,
        tiers=tiers,
        peak_hours_only=peak_hours_only,
        min_rating=min_rating,
        budget=budget,
        status=QuestStatus.LIVE if launch else QuestStatus.DRAFT,
        created_by=user,
    )
    if ride_types:
        quest.ride_types.set(ride_types)
    if launch:
        _announce(quest)
    return quest


def _drivers_for(quest: Quest):
    from apps.drivers.models import DriverProfile, OnboardingStatus

    drivers = DriverProfile.objects.filter(onboarding_status=OnboardingStatus.APPROVED)
    if quest.city_id:
        drivers = drivers.filter(city_id=quest.city_id)
    else:
        drivers = drivers.filter(city__state=quest.state)
    types = list(quest.ride_types.values_list("pk", flat=True))
    if types:
        drivers = drivers.filter(vehicles__ride_type__in=types, vehicles__is_active=True).distinct()
    return drivers.select_related("user")


def _announce(quest: Quest) -> int:
    top_trips, top_reward = quest.tiers[-1]
    sent = 0
    for driver in _drivers_for(quest):
        notify(
            driver.user,
            f"New quest: {quest.name}",
            f"Up to ₹{Decimal(top_reward):g} for {top_trips} trips by "
            f"{timezone.localtime(quest.ends_at):%a %d %b, %I %p}.",
            level=Level.SUCCESS,
            link="/drive/earnings",
        )
        sent += 1
    return sent


def launch(quest: Quest, *, user) -> Quest:
    if quest.status != QuestStatus.DRAFT:
        raise InvalidStateTransition("Only a draft quest can be launched.")
    quest.status = QuestStatus.LIVE
    quest.save(update_fields=["status", "updated_at"])
    _announce(quest)
    return quest


def cancel(quest: Quest, *, user) -> Quest:
    if quest.status not in (QuestStatus.DRAFT, QuestStatus.LIVE):
        raise InvalidStateTransition("This quest is already over.")
    quest.status = QuestStatus.CANCELLED
    quest.save(update_fields=["status", "updated_at"])
    return quest


def _qualifies(quest: Quest, trip) -> bool:
    at = trip.completed_at
    if not quest.starts_at <= at < quest.ends_at:
        return False
    if quest.city_id and trip.city_id != quest.city_id:
        return False
    if not quest.city_id and trip.city.state != quest.state:
        return False
    types = [rt.pk for rt in quest.ride_types.all()]
    if types and trip.ride_type_id not in types:
        return False
    if quest.peak_hours_only and not any(timezone.localtime(at).hour in r for r in PEAK_HOURS):
        return False
    return not (quest.min_rating and trip.driver.rating < quest.min_rating)


def on_trip_completed(trip) -> Decimal:
    """Count a completed trip towards every live quest it qualifies for; pay reached tiers."""
    paid = Decimal(0)
    quests = Quest.objects.filter(
        status=QuestStatus.LIVE, starts_at__lte=trip.completed_at, ends_at__gt=trip.completed_at
    ).filter(Q(city_id=trip.city_id) | Q(city__isnull=True, state=trip.city.state))
    for quest in quests.prefetch_related("ride_types"):
        if _qualifies(quest, trip):
            paid += _count(quest, trip)
    return paid


@transaction.atomic
def _count(quest: Quest, trip) -> Decimal:
    progress, _ = QuestProgress.objects.select_for_update().get_or_create(
        quest=quest, driver=trip.driver
    )
    progress.trips += 1
    reached = sum(1 for trips, _ in quest.tiers if progress.trips >= trips)
    reward = Decimal(0)
    if reached > progress.tiers_paid:
        total = Decimal(quest.tiers[reached - 1][1])
        reward = total - progress.earned
        quest = Quest.objects.select_for_update().get(pk=quest.pk)
        if quest.spent + reward > quest.budget:
            if quest.status == QuestStatus.LIVE:
                quest.status = QuestStatus.ENDED
                quest.save(update_fields=["status", "updated_at"])
                notify_role(
                    Role.OPS_MANAGER,
                    f"Quest {quest.name} ran out of budget",
                    f"₹{quest.spent} of ₹{quest.budget} paid. It has been ended.",
                    level=Level.WARNING,
                )
            progress.save()
            return Decimal(0)
        post(
            TransactionKind.INCENTIVE,
            [(accounts.PLATFORM_PROMOTIONS, -reward), (ensure_wallet(trip.driver.user), reward)],
            trip=trip,
            description=f"{quest.name}: {quest.tiers[reached - 1][0]} trips",
            at=trip.completed_at,
        )
        Quest.objects.filter(pk=quest.pk).update(spent=quest.spent + reward)
        progress.tiers_paid, progress.earned = reached, total
        notify(
            trip.driver.user,
            f"Quest reward: ₹{reward:g}",
            f"{quest.name}: {progress.trips} trips done.",
            level=Level.SUCCESS,
            link="/drive/earnings",
        )
    progress.save()
    return reward


def end_finished(*, now: datetime | None = None) -> int:
    now = now or timezone.now()
    return Quest.objects.filter(status=QuestStatus.LIVE, ends_at__lte=now).update(
        status=QuestStatus.ENDED, updated_at=now
    )


def for_driver(driver, *, now: datetime | None = None) -> list[dict]:
    now = now or timezone.now()
    quests = (
        Quest.objects.filter(status=QuestStatus.LIVE, ends_at__gt=now)
        .filter(Q(city_id=driver.city_id) | Q(city__isnull=True, state=driver.city.state))
        .prefetch_related("ride_types")
    )
    mine = {p.quest_id: p for p in QuestProgress.objects.filter(driver=driver, quest__in=quests)}
    vehicle = driver.active_vehicle
    rows = []
    for quest in quests:
        types = list(quest.ride_types.all())
        if types and (vehicle is None or vehicle.ride_type_id not in {t.pk for t in types}):
            continue
        progress = mine.get(quest.pk)
        trips = progress.trips if progress else 0
        next_tier = next((t for t in quest.tiers if trips < t[0]), None)
        rows.append(
            {
                "id": quest.pk,
                "name": quest.name,
                "ends_at": quest.ends_at.isoformat(),
                "starts_at": quest.starts_at.isoformat(),
                "tiers": quest.tiers,
                "trips": trips,
                "earned": str(progress.earned if progress else 0),
                "next_tier": next_tier,
                "peak_hours_only": quest.peak_hours_only,
                "ride_types": [t.name for t in types],
                "started": quest.starts_at <= now,
            }
        )
    return rows


def stats(quest: Quest) -> dict:
    agg = quest.progress.aggregate(
        drivers=Count("pk"),
        trips=Sum("trips"),
        finished=Count("pk", filter=Q(tiers_paid=len(quest.tiers))),
    )
    return {
        "drivers": agg["drivers"],
        "trips": agg["trips"] or 0,
        "finished": agg["finished"],
        "spent": str(quest.spent),
        "budget_used_percent": round(100 * quest.spent / quest.budget) if quest.budget else 0,
    }
