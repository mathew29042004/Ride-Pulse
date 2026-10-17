"""Demo rosters: this week and next for every state's support desk, a few leave requests
waiting for approval and one approved (with its cover)."""

import random
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.notifications import services as notifications

from . import roster
from .models import LeaveRequest, Shift


def seed(*, seed: int = 61, log=print) -> dict:
    if Shift.objects.exists():
        return {"shifts": 0}
    rng = random.Random(seed)
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    states = sorted(set(StaffProfile.objects.exclude(state="").values_list("state", flat=True)))
    made = leave = 0
    with notifications.muted():
        for state in states:
            if not roster.agents_in(state).exists():
                continue
            for week in (monday, monday + timedelta(days=7)):
                made += roster.generate_week(state, week)["shifts"]
            agents = list(roster.agents_in(state)[:20])
            for agent in rng.sample(agents, min(2, len(agents))):
                start = today + timedelta(days=rng.randint(3, 12))
                roster.request_leave(
                    agent,
                    kind=rng.choice(["CASUAL", "EARNED", "SICK"]),
                    starts_on=start,
                    ends_on=start + timedelta(days=rng.randint(0, 2)),
                    reason=rng.choice(
                        ["Family function", "Medical appointment", "Travel home", ""]
                    ),
                )
                leave += 1
        pending = (
            LeaveRequest.objects.filter(status="PENDING")
            .select_related("user__staff_profile__reports_to__user")
            .first()
        )
        if pending and pending.user.staff_profile.reports_to:
            roster.decide(
                pending,
                manager=pending.user.staff_profile.reports_to.user,
                approve=True,
                note="Enjoy!",
            )
    log(f"Rosters: {made} shifts over two weeks in {len(states)} states, {leave} leave requests")
    return {"shifts": made, "leave_requests": leave}
