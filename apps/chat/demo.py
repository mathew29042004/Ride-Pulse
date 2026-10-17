"""Demo team chat: the standard channels, two days of everyday ops chatter, and a direct
message waiting for the admin."""

import random
from datetime import datetime, timedelta

from django.utils import timezone

from . import services
from .models import Conversation, ConversationKind, Message

CHATTER = {
    "general": [
        "Good morning team! Monsoon alert for tomorrow in Chennai, plan driver cover early.",
        "Reminder: town hall on Friday at 4 pm.",
        "Great week everyone, completed trips up 8% 👏",
        "New help centre articles are live, please share with your teams.",
    ],
    "operations": [
        "T. Nagar is short on drivers this evening, nudging the nearby ones.",
        "Airport queue looks healthy, 14 cars waiting.",
        "Can someone check why Velachery surge stayed high for an hour?",
        "Flood-prone zones list updated for this week.",
    ],
    "support": [
        "Refund queue is down to 6, thanks all.",
        "Two lost phones reported from last night, both found by drivers.",
        "Please use the saved reply for fare disputes, it's been updated.",
        "SLA breaches are zero today 🎉",
    ],
    "maintenance": [
        "3 cars off the road in Bengaluru after daily checks, workshop booked.",
        "Service overdue list sent to fleet owners.",
        "EV chargers at Whitefield are back online.",
    ],
    "rides": [
        "Pickup ETA is under 5 minutes in most zones today.",
        "Shared rides crossed 1,000 this week.",
    ],
    "intercity": [
        "Mahabalipuram tours are fully booked this Saturday.",
        "Toll estimates now show on outstation fares.",
    ],
    "parcels": ["Parcel deliveries on time: 96% this week."],
}


def seed(*, seed: int = 41, log=print, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    stats = services.sync_channels(now=now)
    if Message.objects.exists():
        return stats
    rng = random.Random(seed)
    log("Team chat: channels, a couple of days of messages, a DM for the admin…")
    made = 0
    for slug, lines in CHATTER.items():
        channel = Conversation.objects.filter(kind=ConversationKind.CHANNEL, slug=slug).first()
        if channel is None:
            continue
        people = list(channel.members.values_list("user_id", flat=True))
        if not people:
            continue
        for line in lines:
            at = now - timedelta(hours=rng.randint(2, 44), minutes=rng.randint(0, 59))
            Message.objects.create(
                conversation=channel, author_id=rng.choice(people), body=line, created_at=at
            )
            made += 1
            if rng.random() < 0.5:
                Message.objects.create(
                    conversation=channel,
                    author_id=rng.choice(people),
                    body=rng.choice(services.REPLIES["other"] + services.REPLIES["thanks"]),
                    created_at=at + timedelta(minutes=rng.randint(1, 20)),
                )
                made += 1
        latest = channel.messages.order_by("-created_at").first()
        Conversation.objects.filter(pk=channel.pk).update(last_message_at=latest.created_at)
    from apps.accounts.models import User

    admin = User.objects.filter(email="admin@ridepulse.dev").first()
    lead = (
        User.objects.filter(
            staff_profile__department="SUPPORT", staff_profile__reports_to__isnull=False
        )
        .exclude(pk=getattr(admin, "pk", None))
        .order_by("pk")
        .first()
    )
    if admin and lead:
        dm = services.open_direct(admin, lead.pk, now=now)
        msg = Message.objects.create(
            conversation=dm,
            author=lead,
            body="Hi! The weekend support roster is ready. Shall I share it in #support?",
            created_at=now - timedelta(minutes=40),
        )
        Conversation.objects.filter(pk=dm.pk).update(last_message_at=msg.created_at)
        made += 1
    return {**stats, "chat_messages": made}
