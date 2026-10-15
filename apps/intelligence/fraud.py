"""Fraud detection: rules over the last two weeks of trips open cases in a review queue.

Each rule looks for a pattern honest users rarely produce, scores how strong the evidence is
(0-100) and keeps the trips behind it. A reviewer confirms (and can suspend the driver or block
the rider in the same step) or dismisses. One open case per person and pattern; a dismissed
case can reopen only if the pattern gets worse.

* GPS spoofing: a driver whose phone "teleported" on several trips (GPS_JUMP flags).
* Route padding: a driver whose trips keep running much longer than the planned route.
* Collusion: the same rider and driver completing trip after trip together (fake trips to
  farm incentives or launder promo money).
* Promo abuse: a rider redeeming promo codes on very short trips.
* Referral farming: one referrer whose many new referees each took a single trip or none.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition
from apps.core.sequences import next_reference
from apps.notifications.models import Level
from apps.notifications.services import notify_role
from apps.riders.models import RiderProfile
from apps.rides.models import Trip, TripFlag, TripStatus

from .models import FraudCase, FraudKind, FraudStatus

WINDOW = timedelta(days=14)
GPS_JUMPS = 2
PADDED_TRIPS = 3
PAIR_TRIPS = 4
SHORT_KM = 1.0
SHORT_PROMO_TRIPS = 3
REFEREES = 4


def _score(count: int, threshold: int, base: int = 55) -> int:
    return min(99, base + 12 * (count - threshold))


def _detect(now: datetime) -> list[dict]:
    since = now - WINDOW
    done = Trip.objects.filter(status=TripStatus.COMPLETED, completed_at__gte=since)
    found = []

    for row in (
        done.filter(flags__contains=[TripFlag.GPS_JUMP])
        .values("driver_id", "city_id")
        .annotate(n=Count("pk"))
        .filter(n__gte=GPS_JUMPS)
    ):
        trips = done.filter(driver_id=row["driver_id"], flags__contains=[TripFlag.GPS_JUMP])
        found.append(
            {
                "kind": FraudKind.GPS_SPOOFING,
                "driver_id": row["driver_id"],
                "city_id": row["city_id"],
                "score": _score(row["n"], GPS_JUMPS, 65),
                "summary": f"GPS jumped impossibly far on {row['n']} trips in 14 days",
                "evidence": {"gps_jump_trips": row["n"]},
                "trip_ids": list(trips.values_list("pk", flat=True)[:20]),
            }
        )

    for row in (
        done.filter(flags__contains=[TripFlag.ROUTE_DEVIATION])
        .values("driver_id", "city_id")
        .annotate(n=Count("pk"))
        .filter(n__gte=PADDED_TRIPS)
    ):
        trips = done.filter(driver_id=row["driver_id"], flags__contains=[TripFlag.ROUTE_DEVIATION])
        total = done.filter(driver_id=row["driver_id"]).count()
        found.append(
            {
                "kind": FraudKind.ROUTE_PADDING,
                "driver_id": row["driver_id"],
                "city_id": row["city_id"],
                "score": _score(row["n"], PADDED_TRIPS, 50),
                "summary": f"{row['n']} of {total} trips ran much longer than the planned route",
                "evidence": {"padded_trips": row["n"], "trips": total},
                "trip_ids": list(trips.values_list("pk", flat=True)[:20]),
            }
        )

    for row in (
        done.values("driver_id", "rider_id", "city_id")
        .annotate(n=Count("pk"))
        .filter(n__gte=PAIR_TRIPS)
    ):
        trips = done.filter(driver_id=row["driver_id"], rider_id=row["rider_id"])
        found.append(
            {
                "kind": FraudKind.COLLUSION,
                "driver_id": row["driver_id"],
                "rider_id": row["rider_id"],
                "city_id": row["city_id"],
                "score": _score(row["n"], PAIR_TRIPS, 60),
                "summary": f"Same rider and driver on {row['n']} trips in 14 days",
                "evidence": {"pair_trips": row["n"]},
                "trip_ids": list(trips.values_list("pk", flat=True)[:20]),
            }
        )

    short_promo = done.filter(promo__isnull=False, actual_distance_km__lt=SHORT_KM)
    for row in (
        short_promo.values("rider_id", "city_id")
        .annotate(n=Count("pk"))
        .filter(n__gte=SHORT_PROMO_TRIPS)
    ):
        trips = short_promo.filter(rider_id=row["rider_id"])
        found.append(
            {
                "kind": FraudKind.PROMO_ABUSE,
                "rider_id": row["rider_id"],
                "city_id": row["city_id"],
                "score": _score(row["n"], SHORT_PROMO_TRIPS, 55),
                "summary": f"Promo codes used on {row['n']} trips under {SHORT_KM:g} km",
                "evidence": {"short_promo_trips": row["n"]},
                "trip_ids": list(trips.values_list("pk", flat=True)[:20]),
            }
        )

    referees = RiderProfile.objects.filter(
        referred_by__isnull=False, created_at__gte=now - timedelta(days=30), completed_trips__lte=1
    )
    for row in referees.values("referred_by_id").annotate(n=Count("pk")).filter(n__gte=REFEREES):
        found.append(
            {
                "kind": FraudKind.REFERRAL_FARMING,
                "rider_id": row["referred_by_id"],
                "city_id": None,
                "score": _score(row["n"], REFEREES, 55),
                "summary": f"{row['n']} new referrals in 30 days took one trip or none",
                "evidence": {"idle_referees": row["n"]},
                "trip_ids": [],
            }
        )
    return found


@transaction.atomic
def scan(*, now: datetime | None = None) -> dict:
    """Run every rule; open new cases and strengthen open ones."""
    now = now or timezone.now()
    opened = updated = 0
    for hit in _detect(now):
        key = {
            "kind": hit["kind"],
            "driver_id": hit.get("driver_id"),
            "rider_id": hit.get("rider_id"),
        }
        case = FraudCase.objects.filter(status=FraudStatus.OPEN, **key).first()
        if case:
            if hit["score"] > case.score:
                case.score, case.summary = hit["score"], hit["summary"]
                case.evidence, case.trip_ids = hit["evidence"], hit["trip_ids"]
                case.save(update_fields=["score", "summary", "evidence", "trip_ids"])
                updated += 1
            continue
        dismissed = (
            FraudCase.objects.filter(status=FraudStatus.DISMISSED, **key).order_by("-score").first()
        )
        if dismissed and hit["score"] <= dismissed.score:
            continue  # already judged innocent; only reopen if it gets worse
        if FraudCase.objects.filter(status=FraudStatus.CONFIRMED, **key).exists():
            continue
        case = FraudCase.objects.create(
            number=next_reference("FRD", year=timezone.localtime(now).year),
            city_id=hit["city_id"],
            score=hit["score"],
            summary=hit["summary"],
            evidence=hit["evidence"],
            trip_ids=hit["trip_ids"],
            created_at=now,
            **key,
        )
        opened += 1
        if case.score >= 75:
            notify_role(
                "ADMIN",
                f"Fraud case {case.number}: {case.get_kind_display()}",
                case.summary,
                level=Level.WARNING,
                link=f"/ops/fraud?case={case.pk}",
            )
    return {"opened": opened, "updated": updated}


ACTIONS = ("NONE", "SUSPEND_DRIVER", "BLOCK_RIDER")


@transaction.atomic
def review(
    case: FraudCase, *, user, confirm: bool, note: str = "", action: str = "NONE"
) -> FraudCase:
    from apps.drivers.services import suspend_driver
    from apps.riders.services import set_blocked

    case = FraudCase.objects.select_for_update().get(pk=case.pk)
    if case.status != FraudStatus.OPEN:
        raise InvalidStateTransition("This case has already been reviewed.")
    if action not in ACTIONS or (action != "NONE" and not confirm):
        raise BusinessRuleViolation("Choose an action only when confirming fraud.", field="action")
    reason = f"Fraud case {case.number}: {case.get_kind_display().lower()}. {note}".strip()
    if action == "SUSPEND_DRIVER":
        if case.driver is None:
            raise BusinessRuleViolation("This case has no driver.", field="action")
        suspend_driver(case.driver, reason=reason, actor=user)
    elif action == "BLOCK_RIDER":
        if case.rider is None:
            raise BusinessRuleViolation("This case has no rider.", field="action")
        set_blocked(case.rider, True, reason=reason, actor=user)
    case.status = FraudStatus.CONFIRMED if confirm else FraudStatus.DISMISSED
    case.reviewed_by, case.reviewed_at = user, timezone.now()
    case.review_note, case.action_taken = note.strip(), action
    case.save()
    return case


def summary() -> dict:
    open_cases = FraudCase.objects.filter(status=FraudStatus.OPEN)
    return {
        "open": open_cases.count(),
        "high_risk": open_cases.filter(score__gte=75).count(),
        "by_kind": dict(
            open_cases.values_list("kind").annotate(n=Count("pk")).values_list("kind", "n")
        ),
        "confirmed_30d": FraudCase.objects.filter(
            status=FraudStatus.CONFIRMED, reviewed_at__gte=timezone.now() - timedelta(days=30)
        ).count(),
    }
