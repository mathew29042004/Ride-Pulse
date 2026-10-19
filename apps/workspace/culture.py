"""Small things that make a team: celebrations and shift handovers.

* Celebrations: every morning, birthdays and work anniversaries are posted to #general (once a
  day each), and the person gets a note.
* Handover notes: whoever ends a shift leaves a note for the next person in the same role and
  city ("Two drivers still waiting on documents; Kochi airport queue was long"). The next person
  sees the latest notes when they clock in, and on their attendance page, for 24 hours.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation


class HandoverNote(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    role = models.CharField(max_length=24, db_index=True)
    city = models.ForeignKey(
        "geo.City", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        app_label = "workspace"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Handover by {self.author_id}"


def leave_handover(user, body: str, *, now=None) -> HandoverNote:
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        raise BusinessRuleViolation("Handover notes are for staff.")
    if len(body.strip()) < 5:
        raise BusinessRuleViolation("Write what the next person needs to know.", field="body")
    return HandoverNote.objects.create(
        author=user,
        role=user.role,
        city=profile.city,
        body=body.strip()[:2000],
        created_at=now or timezone.now(),
    )


def handovers_for(user, *, now=None) -> list[dict]:
    """The last day's notes from others in my role and city."""
    profile = getattr(user, "staff_profile", None)
    if profile is None:
        return []
    now = now or timezone.now()
    notes = (
        HandoverNote.objects.filter(
            role=user.role, city=profile.city, created_at__gte=now - timedelta(hours=24)
        )
        .exclude(author=user)
        .select_related("author")[:5]
    )
    return [
        {
            "id": n.pk,
            "author": n.author.get_full_name(),
            "body": n.body,
            "created_at": n.created_at.isoformat(),
        }
        for n in notes
    ]


def celebrate(*, now=None) -> dict:
    """Post today's birthdays and work anniversaries to #general (once each per day)."""
    from apps.accounts.models import StaffProfile
    from apps.chat.models import Conversation, Message
    from apps.chat.services import _deliver
    from apps.notifications.services import notify

    now = now or timezone.now()
    today = timezone.localdate(now)
    general = Conversation.objects.filter(kind="CHANNEL", slug="general").first()
    if general is None:
        return {"posted": 0}
    posted = 0
    people = StaffProfile.objects.filter(user__is_active=True).select_related("user")
    for p in people:
        lines = []
        if p.date_of_birth and (p.date_of_birth.month, p.date_of_birth.day) == (
            today.month,
            today.day,
        ):
            lines.append(f"🎂 Happy birthday, {p.user.get_full_name()} ({p.title})!")
        years = today.year - p.joined_on.year
        if years >= 1 and (p.joined_on.month, p.joined_on.day) == (today.month, today.day):
            lines.append(
                f"🎉 {p.user.get_full_name()} completes {years} year{'s' if years > 1 else ''} "
                "at Ride Pulse today. Thank you!"
            )
        for line in lines:
            start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            if Message.objects.filter(
                conversation=general, author=None, body=line, created_at__gte=start
            ).exists():
                continue
            message = Message.objects.create(conversation=general, body=line, created_at=now)
            Conversation.objects.filter(pk=general.pk).update(last_message_at=now)
            _deliver(general, message)
            notify(p.user, "From everyone at Ride Pulse", line, link="/ops/chat")
            posted += 1
    return {"posted": posted}


def seed_birthdays(*, seed: int = 21, log=print) -> dict:
    """A date of birth for every employee who doesn't have one (a few fall in the next week)."""
    import random
    from datetime import date

    from apps.accounts.models import StaffProfile

    rng = random.Random(seed)
    today = timezone.localdate()
    rows = list(StaffProfile.objects.filter(date_of_birth__isnull=True))
    for i, p in enumerate(rows):
        if i < 4:  # some birthdays this week, so the feature shows
            soon = today + timedelta(days=i * 2)
            p.date_of_birth = date(today.year - rng.randint(24, 50), soon.month, soon.day)
        else:
            p.date_of_birth = date(rng.randint(1975, 2001), rng.randint(1, 12), rng.randint(1, 28))
    StaffProfile.objects.bulk_update(rows, ["date_of_birth"])
    log(f"  birthdays: {len(rows)}")
    return {"birthdays": len(rows)}
