"""Demo announcements in English and Tamil, with realistic read rates."""

import random
from datetime import timedelta

from django.utils import timezone

from apps.notifications import services as notifications

from . import services
from .models import Announcement, AnnouncementRead

ITEMS = [
    (
        "DRIVERS",
        "Tamil Nadu",
        True,
        4,
        {
            "en": {
                "title": "Heavy rain expected tomorrow",
                "body": "Avoid flooded underpasses and drive slowly. Surge stays capped at 2x under state rules.",
            },
            "ta": {
                "title": "நாளை கனமழை எதிர்பார்க்கப்படுகிறது",
                "body": "வெள்ளம் உள்ள சுரங்கப்பாதைகளைத் தவிர்த்து மெதுவாக ஓட்டுங்கள்.",
            },
        },
    ),
    (
        "DRIVERS",
        "",
        False,
        9,
        {
            "en": {
                "title": "New: Driver Academy",
                "body": "Short courses on first aid, EVs and helping riders with disabilities. Find them in Account.",
            }
        },
    ),
    (
        "RIDERS",
        "",
        False,
        6,
        {
            "en": {
                "title": "Tours are here",
                "body": "Day trips to famous places at a fixed price, with your own driver. Tap Tours on Home.",
            }
        },
    ),
    (
        "STAFF",
        "",
        False,
        2,
        {
            "en": {
                "title": "Two-step sign-in for managers",
                "body": "Admins and managers: please turn on two-step sign-in under Security this week.",
            }
        },
    ),
]


def seed(*, seed: int = 71, log=print) -> dict:
    if Announcement.objects.exists():
        return {"announcements": 0}
    rng = random.Random(seed)
    now = timezone.now()
    with notifications.muted():
        for audience, state, important, days_ago, text in ITEMS:
            a = services.publish(
                user=None,
                audience=audience,
                state=state,
                important=important,
                text=text,
                now=now - timedelta(days=days_ago),
            )
            share = rng.uniform(0.45, 0.85)
            people = list(services.audience_users(a).values_list("pk", flat=True))
            AnnouncementRead.objects.bulk_create(
                [
                    AnnouncementRead(
                        announcement=a,
                        user_id=pk,
                        read_at=a.published_at + timedelta(hours=rng.randint(1, 48)),
                    )
                    for pk in people
                    if rng.random() < share
                ],
                batch_size=2000,
            )
    log(f"Announcements: {len(ITEMS)} sent")
    return {"announcements": len(ITEMS)}
