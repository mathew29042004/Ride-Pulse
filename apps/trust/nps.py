"""NPS: "How likely are you to recommend Ride Pulse to a friend?" (0–10).

* **Who and when**: riders after 3 completed rides, drivers after 10; at most once every 90
  days; "not now" snoozes it 30 days.
* **Score**: % promoters (9–10) minus % detractors (0–6), from -100 to +100, by audience, city
  and month.
* **Themes** in comments come from simple keyword rules (price, waiting, driver behaviour,
  vehicle, app, safety, payments). It's a rough grouping, not AI; AI theming would come with the
  assistant (on hold).
"""

import re
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

from .models import NpsAudience, NpsPrompt, NpsResponse

EVERY = timedelta(days=90)
SNOOZE = timedelta(days=30)
MIN_TRIPS = {NpsAudience.RIDER: 3, NpsAudience.DRIVER: 10}
THEMES = {
    "Price": ["price", "expensive", "costly", "fare", "surge", "cheap", "charge"],
    "Waiting time": ["wait", "late", "delay", "eta", "long time", "no driver", "slow"],
    "Driver behaviour": ["rude", "polite", "behav", "friendly", "driver was", "attitude"],
    "Vehicle": ["clean", "dirty", "ac ", "a/c", "smell", "car condition", "seat"],
    "App": ["app", "crash", "bug", "map", "gps", "login"],
    "Safety": ["safe", "unsafe", "speed", "rash", "night"],
    "Payments": ["payment", "upi", "refund", "wallet", "cash"],
    "Earnings": ["earning", "commission", "incentive", "payout", "income"],
}


def _audience(user) -> str | None:
    if user.is_rider:
        return NpsAudience.RIDER
    if user.is_driver:
        return NpsAudience.DRIVER
    return None


def _trips(user, audience) -> int:
    """Read fresh: a profile loaded earlier in the request may be out of date."""
    from apps.drivers.models import DriverProfile
    from apps.riders.models import RiderProfile

    model = RiderProfile if audience == NpsAudience.RIDER else DriverProfile
    return model.objects.filter(user=user).values_list("completed_trips", flat=True).first() or 0


def should_ask(user, *, now=None) -> bool:
    now = now or timezone.now()
    audience = _audience(user)
    if audience is None or _trips(user, audience) < MIN_TRIPS[audience]:
        return False
    prompt = NpsPrompt.objects.filter(user=user).first()
    return prompt is None or prompt.next_ask_after <= now


def _city(user, audience):
    if audience == NpsAudience.DRIVER:
        return user.driver_profile.city_id
    trip = (
        user.rider_profile.trips.order_by("-requested_at").values_list("city_id", flat=True).first()
    )
    return trip


def answer(user, *, score: int, comment: str = "", now=None) -> NpsResponse:
    now = now or timezone.now()
    audience = _audience(user)
    if audience is None:
        raise BusinessRuleViolation("Only riders and drivers are surveyed.")
    if not 0 <= int(score) <= 10:
        raise BusinessRuleViolation("Choose a score from 0 to 10.", field="score")
    response = NpsResponse.objects.create(
        user=user,
        audience=audience,
        score=int(score),
        comment=comment.strip()[:500],
        city_id=_city(user, audience),
        created_at=now,
    )
    NpsPrompt.objects.update_or_create(user=user, defaults={"next_ask_after": now + EVERY})
    return response


def snooze(user, *, now=None) -> None:
    now = now or timezone.now()
    NpsPrompt.objects.update_or_create(user=user, defaults={"next_ask_after": now + SNOOZE})


def _nps(rows) -> int | None:
    total = len(rows) if isinstance(rows, list) else None
    return (
        None
        if not total
        else round(100 * (sum(r >= 9 for r in rows) - sum(r <= 6 for r in rows)) / total)
    )


def themes(comments: list[str]) -> list[dict]:
    counts: Counter = Counter()
    for comment in comments:
        text = f" {comment.lower()} "
        for theme, words in THEMES.items():
            # Keywords match at the start of a word, so "crashed" isn't "rash".
            if any(re.search(r"\b" + re.escape(w), text) for w in words):
                counts[theme] += 1
    return [{"theme": t, "mentions": n} for t, n in counts.most_common()]


def report(*, days: int = 90, now=None) -> dict:
    now = now or timezone.now()
    rows = NpsResponse.objects.filter(created_at__gte=now - timedelta(days=days)).select_related(
        "city"
    )
    out = {}
    for audience in NpsAudience.values:
        mine = [r for r in rows if r.audience == audience]
        scores = [r.score for r in mine]
        by_city: dict[str, list[int]] = {}
        for r in mine:
            by_city.setdefault(r.city.name if r.city_id else "Unknown", []).append(r.score)
        months: dict[str, list[int]] = {}
        for r in mine:
            months.setdefault(timezone.localtime(r.created_at).strftime("%Y-%m"), []).append(
                r.score
            )
        detractor_comments = [r.comment for r in mine if r.comment and r.score <= 6]
        promoter_comments = [r.comment for r in mine if r.comment and r.score >= 9]
        out[audience] = {
            "responses": len(scores),
            "nps": _nps(scores),
            "promoters": sum(s >= 9 for s in scores),
            "passives": sum(7 <= s <= 8 for s in scores),
            "detractors": sum(s <= 6 for s in scores),
            "by_city": sorted(
                (
                    {"city": c, "nps": _nps(v), "responses": len(v)}
                    for c, v in by_city.items()
                    if len(v) >= 5
                ),
                key=lambda x: x["nps"],
            ),
            "by_month": [
                {"month": m, "nps": _nps(v), "responses": len(v)} for m, v in sorted(months.items())
            ],
            "detractor_themes": themes(detractor_comments),
            "promoter_themes": themes(promoter_comments),
            "recent_comments": [
                {"score": r.score, "comment": r.comment, "city": r.city.name if r.city_id else ""}
                for r in mine
                if r.comment
            ][:15],
        }
    return out
