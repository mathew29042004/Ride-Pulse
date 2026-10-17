"""Shifts and leave for the support desks.

* **How many agents**: from the last 4 weeks of tickets in the state, the busiest hour of each
  shift on that weekday, at ``TICKETS_PER_AGENT_HOUR`` per agent, never below the minimum cover.
* **The roster** for a week is filled shift by shift: people on approved leave are skipped, nobody
  works more than ``MAX_SHIFTS_PER_WEEK``, two shifts on one day, or a morning straight after a
  night (they need ``MIN_REST`` between shifts), and the load is spread evenly.
* **Leave** goes to the person's manager (anyone above them in the org chart). Approving it takes
  them off their shifts and finds someone to cover each one (or flags the gap).
* **On duty now**: new support tickets go to agents who are on shift (if anyone is rostered).
"""

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay
from django.utils import timezone

from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, InvalidStateTransition
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import LeaveRequest, LeaveStatus, Shift, ShiftSlot

SLOT_HOURS = {ShiftSlot.MORNING: (6, 14), ShiftSlot.EVENING: (14, 22), ShiftSlot.NIGHT: (22, 30)}
MIN_AGENTS = {ShiftSlot.MORNING: 2, ShiftSlot.EVENING: 2, ShiftSlot.NIGHT: 1}
TICKETS_PER_AGENT_HOUR = 3
MAX_SHIFTS_PER_WEEK = 6
MIN_REST = timedelta(hours=11)


def _bounds(day: date, slot: str) -> tuple[datetime, datetime]:
    start, end = SLOT_HOURS[slot]
    midnight = timezone.make_aware(datetime.combine(day, time()))
    return midnight + timedelta(hours=start), midnight + timedelta(hours=end)


def agents_in(state: str):
    from apps.accounts.models import Role, User

    return User.objects.filter(
        role=Role.SUPPORT_AGENT, is_active=True, staff_profile__state=state
    ).order_by("pk")


def demand(state: str, *, today: date | None = None) -> dict[tuple[int, int], float]:
    """Average tickets per (ISO weekday, hour) in the state over the last 4 weeks."""
    from apps.support.models import SupportTicket

    today = today or timezone.localdate()
    since = timezone.make_aware(datetime.combine(today - timedelta(days=28), time()))
    rows = (
        SupportTicket.objects.filter(created_at__gte=since, trip__city__state=state)
        .annotate(dow=ExtractIsoWeekDay("created_at"), hour=ExtractHour("created_at"))
        .values("dow", "hour")
        .annotate(n=Count("pk"))
    )
    return {(r["dow"], r["hour"]): r["n"] / 4 for r in rows}


def needed(state: str, day: date, slot: str, forecast: dict | None = None) -> int:
    forecast = demand(state) if forecast is None else forecast
    start, end = SLOT_HOURS[slot]
    peak = max(
        forecast.get(((day + timedelta(days=h // 24)).isoweekday(), h % 24), 0.0)
        for h in range(start, end)
    )
    return max(MIN_AGENTS[slot], math.ceil(peak / TICKETS_PER_AGENT_HOUR))


def _on_leave(user_ids, start: date, end: date) -> dict[int, set[date]]:
    out: dict[int, set[date]] = defaultdict(set)
    for leave in LeaveRequest.objects.filter(
        user_id__in=user_ids, status=LeaveStatus.APPROVED, starts_on__lte=end, ends_on__gte=start
    ):
        d = max(leave.starts_on, start)
        while d <= min(leave.ends_on, end):
            out[leave.user_id].add(d)
            d += timedelta(days=1)
    return out


def _can_work(
    user_id: int, day: date, slot: str, taken: dict, leave: dict, week_start: date
) -> bool:
    if day in leave.get(user_id, ()):
        return False
    mine = taken.get(user_id, [])
    if any(d == day for d, _ in mine):
        return False
    if (
        sum(1 for d, _ in mine if week_start <= d < week_start + timedelta(days=7))
        >= MAX_SHIFTS_PER_WEEK
    ):
        return False
    start, end = _bounds(day, slot)
    for d, s in mine:
        other_start, other_end = _bounds(d, s)
        if other_end <= start and start - other_end < MIN_REST:
            return False
        if end <= other_start and other_start - end < MIN_REST:
            return False
    return True


@transaction.atomic
def generate_week(state: str, week_start: date, *, replace: bool = False) -> dict:
    """Fill Monday–Sunday for the state's support agents."""
    week_start = week_start - timedelta(days=week_start.weekday())
    week_end = week_start + timedelta(days=6)
    agents = list(agents_in(state).values_list("pk", flat=True))
    if not agents:
        raise BusinessRuleViolation(f"No support agents in {state}.")
    existing = Shift.objects.filter(state=state, day__range=(week_start, week_end))
    if existing.exists():
        if not replace:
            raise BusinessRuleViolation("This week is already rostered.")
        existing.delete()
    leave = _on_leave(agents, week_start, week_end)
    taken: dict[int, list] = defaultdict(list)
    # Shifts already worked just before the week count for rest between shifts.
    for user_id, d, s in Shift.objects.filter(
        user_id__in=agents,
        day__range=(week_start - timedelta(days=1), week_start - timedelta(days=1)),
    ).values_list("user_id", "day", "slot"):
        taken[user_id].append((d, s))
    forecast = demand(state, today=week_start)
    shifts, gaps = [], []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        for slot in (ShiftSlot.MORNING, ShiftSlot.EVENING, ShiftSlot.NIGHT):
            want = needed(state, day, slot, forecast)
            order = sorted(agents, key=lambda u: (len(taken[u]), u))
            picked = [u for u in order if _can_work(u, day, slot, taken, leave, week_start)][:want]
            start, end = _bounds(day, slot)
            for user_id in picked:
                taken[user_id].append((day, slot))
                shifts.append(
                    Shift(
                        user_id=user_id,
                        day=day,
                        slot=slot,
                        state=state,
                        starts_at=start,
                        ends_at=end,
                    )
                )
            if len(picked) < want:
                gaps.append({"day": day.isoformat(), "slot": slot, "short_by": want - len(picked)})
    Shift.objects.bulk_create(shifts)
    return {
        "state": state,
        "week_start": week_start.isoformat(),
        "shifts": len(shifts),
        "gaps": gaps,
    }


def week_view(state: str, week_start: date) -> dict:
    week_start = week_start - timedelta(days=week_start.weekday())
    forecast = demand(state, today=week_start)
    rows = Shift.objects.filter(
        state=state, day__range=(week_start, week_start + timedelta(days=6))
    ).select_related("user", "covering_for")
    grid: dict[tuple[str, str], list] = defaultdict(list)
    for shift in rows:
        grid[(shift.day.isoformat(), shift.slot)].append(
            {
                "id": shift.pk,
                "user_id": shift.user_id,
                "name": shift.user.get_full_name(),
                "covering_for": shift.covering_for.get_full_name()
                if shift.covering_for_id
                else None,
            }
        )
    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        days.append(
            {
                "day": day.isoformat(),
                "slots": [
                    {
                        "slot": slot,
                        "label": ShiftSlot(slot).label,
                        "needed": needed(state, day, slot, forecast),
                        "people": grid.get((day.isoformat(), slot), []),
                    }
                    for slot in (ShiftSlot.MORNING, ShiftSlot.EVENING, ShiftSlot.NIGHT)
                ],
            }
        )
    return {"state": state, "week_start": week_start.isoformat(), "days": days}


def on_duty(*, now: datetime | None = None) -> set[int]:
    now = now or timezone.now()
    return set(
        Shift.objects.filter(starts_at__lte=now, ends_at__gt=now).values_list("user_id", flat=True)
    )


# --- Leave ----------------------------------------------------------------------------------


def request_leave(user, *, kind: str, starts_on: date, ends_on: date, reason: str = "", now=None):
    now = now or timezone.now()
    if ends_on < starts_on:
        raise BusinessRuleViolation("The leave ends before it starts.", field="ends_on")
    if starts_on < timezone.localdate(now) - timedelta(days=7):
        raise BusinessRuleViolation("Leave can be requested up to a week after the fact.")
    if (ends_on - starts_on).days > 30:
        raise BusinessRuleViolation("Request at most 30 days at a time.")
    if LeaveRequest.objects.filter(
        user=user,
        status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
        starts_on__lte=ends_on,
        ends_on__gte=starts_on,
    ).exists():
        raise BusinessRuleViolation("You already have leave on those days.")
    leave = LeaveRequest.objects.create(
        user=user,
        kind=kind,
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason[:200],
        created_at=now,
    )
    manager = getattr(getattr(user, "staff_profile", None), "reports_to", None)
    if manager is not None:
        notify(
            manager.user,
            f"Leave request from {user.get_full_name()}",
            f"{leave.get_kind_display()}, {starts_on:%d %b}–{ends_on:%d %b}. {reason}".strip(),
            level=Level.INFO,
            link="/ops/roster",
        )
    return leave


def can_decide(manager, leave: LeaveRequest) -> bool:
    from .services import team_of

    return leave.user_id in team_of(manager)


@transaction.atomic
def decide(leave: LeaveRequest, *, manager, approve: bool, note: str = "", now=None) -> dict:
    now = now or timezone.now()
    leave = LeaveRequest.objects.select_for_update().get(pk=leave.pk)
    if not can_decide(manager, leave):
        raise ActionNotPermitted("Only someone above them in the team can decide this.")
    if leave.status != LeaveStatus.PENDING:
        raise InvalidStateTransition("This request has already been decided.")
    leave.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
    leave.decided_by, leave.decided_at, leave.note = manager, now, note[:200]
    leave.save(update_fields=["status", "decided_by", "decided_at", "note"])
    covered, gaps = [], []
    if approve:
        affected = list(
            Shift.objects.filter(user=leave.user, day__range=(leave.starts_on, leave.ends_on))
        )
        for shift in affected:
            cover = _find_cover(shift)
            shift.delete()
            if cover:
                Shift.objects.create(
                    user_id=cover,
                    day=shift.day,
                    slot=shift.slot,
                    state=shift.state,
                    starts_at=shift.starts_at,
                    ends_at=shift.ends_at,
                    covering_for=leave.user,
                )
                covered.append({"day": shift.day.isoformat(), "slot": shift.slot, "user_id": cover})
                from apps.accounts.models import User

                notify(
                    User.objects.get(pk=cover),
                    f"You're covering a {ShiftSlot(shift.slot).label.split(' (')[0].lower()} shift",
                    f"{shift.day:%a %d %b} for {leave.user.get_full_name()} (on leave).",
                    level=Level.INFO,
                    link="/ops/roster",
                )
            else:
                gaps.append({"day": shift.day.isoformat(), "slot": shift.slot})
    notify(
        leave.user,
        f"Leave {'approved' if approve else 'not approved'}",
        f"{leave.starts_on:%d %b}–{leave.ends_on:%d %b}" + (f": {note}" if note else ""),
        level=Level.SUCCESS if approve else Level.WARNING,
        link="/ops/roster",
    )
    return {"status": leave.status, "covered": covered, "gaps": gaps}


def _find_cover(shift: Shift) -> int | None:
    week_start = shift.day - timedelta(days=shift.day.weekday())
    agents = list(agents_in(shift.state).exclude(pk=shift.user_id).values_list("pk", flat=True))
    leave = _on_leave(agents, shift.day, shift.day)
    taken: dict[int, list] = defaultdict(list)
    for user_id, d, s in Shift.objects.filter(
        user_id__in=agents,
        day__range=(week_start - timedelta(days=1), week_start + timedelta(days=7)),
    ).values_list("user_id", "day", "slot"):
        taken[user_id].append((d, s))
    for user_id in sorted(agents, key=lambda u: (len(taken[u]), u)):
        if _can_work(user_id, shift.day, shift.slot, taken, leave, week_start):
            return user_id
    return None
