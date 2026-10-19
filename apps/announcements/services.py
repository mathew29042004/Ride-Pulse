"""Publishing, reading and read rates."""

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation
from apps.notifications.models import Level
from apps.notifications.services import notify

from .models import Announcement, AnnouncementRead, Audience

LANGUAGES = ("en", "ta", "hi", "ml", "kn", "te")


RIDER_RECENT_DAYS = 90


def audience_users(announcement: Announcement):
    """Drivers by their city, staff by their city or state, riders by where they've ridden in
    the last 90 days (riders have no home city)."""
    from datetime import timedelta

    from apps.accounts.models import User

    users = User.objects.filter(is_active=True)
    if announcement.audience == Audience.RIDERS:
        users = users.filter(rider_profile__isnull=False)
        if announcement.city_id or announcement.state:
            since = timezone.now() - timedelta(days=RIDER_RECENT_DAYS)
            where = (
                {"rider_profile__trips__city_id": announcement.city_id}
                if announcement.city_id
                else {"rider_profile__trips__city__state": announcement.state}
            )
            users = users.filter(rider_profile__trips__requested_at__gte=since, **where).distinct()
        return users
    if announcement.audience == Audience.DRIVERS:
        users = users.filter(driver_profile__isnull=False)
        if announcement.city_id:
            return users.filter(driver_profile__city_id=announcement.city_id)
        if announcement.state:
            return users.filter(driver_profile__city__state=announcement.state)
        return users
    users = users.filter(staff_profile__isnull=False)
    if announcement.city_id:
        return users.filter(staff_profile__city_id=announcement.city_id)
    if announcement.state:
        return users.filter(staff_profile__state=announcement.state)
    return users


def publish(
    *, user, audience: str, text: dict, state: str = "", city=None, important=False, now=None
):
    now = now or timezone.now()
    clean = {}
    for lang in LANGUAGES:
        part = text.get(lang) or {}
        title, body = (
            str(part.get("title", "")).strip()[:120],
            str(part.get("body", "")).strip()[:2000],
        )
        if title and body:
            clean[lang] = {"title": title, "body": body}
    if "en" not in clean:
        raise BusinessRuleViolation("Write the English title and message.", field="text")
    if audience not in Audience.values:
        raise BusinessRuleViolation("Choose who it's for.", field="audience")
    announcement = Announcement.objects.create(
        audience=audience,
        state=state if not city else "",
        city=city,
        text=clean,
        important=important,
        created_by=user,
        published_at=now,
    )
    sent = 0
    for person in audience_users(announcement).only("pk", "language").iterator():
        part = announcement.localized(person.language)
        notify(
            person,
            part["title"],
            part["body"][:300],
            level=Level.WARNING if important else Level.INFO,
            link="/drive"
            if audience == Audience.DRIVERS
            else "/ride"
            if audience == Audience.RIDERS
            else "/ops",
        )
        sent += 1
    Announcement.objects.filter(pk=announcement.pk).update(recipients=sent)
    announcement.recipients = sent
    return announcement


def _where(user):
    """The person's audience, city and state (a rider's from their latest trip)."""
    if hasattr(user, "driver_profile") and user.is_driver:
        city = user.driver_profile.city
        return Audience.DRIVERS, city.pk, city.state
    if user.is_rider and hasattr(user, "rider_profile"):
        trip = user.rider_profile.trips.select_related("city").order_by("-requested_at").first()
        return Audience.RIDERS, trip.city_id if trip else None, trip.city.state if trip else ""
    profile = getattr(user, "staff_profile", None) if hasattr(user, "staff_profile") else None
    if profile is not None:
        return Audience.STAFF, profile.city_id, profile.state
    return None, None, ""


def inbox(user, *, limit: int = 20) -> list[dict]:
    """Announcements meant for this person (everywhere, their state or their city), newest
    first, in their language: one query."""
    audience, city_id, state = _where(user)
    if audience is None:
        return []
    place = Q(city__isnull=True, state="") | Q(city__isnull=True, state=state)
    if city_id:
        place |= Q(city_id=city_id)
    rows = Announcement.objects.filter(place, audience=audience).order_by("-published_at")[:limit]
    read = set(
        AnnouncementRead.objects.filter(user=user, announcement__in=rows).values_list(
            "announcement_id", flat=True
        )
    )
    out = []
    for a in rows:
        part = a.localized(user.language)
        out.append(
            {
                "id": a.pk,
                "title": part["title"],
                "body": part["body"],
                "important": a.important,
                "published_at": a.published_at,
                "read": a.pk in read,
            }
        )
    return out


def mark_read(user, announcement_id: int, *, now=None) -> None:
    AnnouncementRead.objects.get_or_create(
        announcement_id=announcement_id, user=user, defaults={"read_at": now or timezone.now()}
    )


def report(*, limit: int = 30) -> list[dict]:
    rows = Announcement.objects.annotate(read=Count("reads")).select_related("city", "created_by")[
        :limit
    ]
    return [
        {
            "id": a.pk,
            "title": a.text["en"]["title"],
            "body": a.text["en"]["body"],
            "languages": list(a.text),
            "audience": a.audience,
            "audience_label": a.get_audience_display(),
            "where": a.city.name if a.city_id else a.state or "Everywhere",
            "important": a.important,
            "published_at": a.published_at,
            "recipients": a.recipients,
            "read": a.read,
            "read_rate": round(a.read / a.recipients, 3) if a.recipients else None,
            "by": a.created_by.get_full_name() if a.created_by_id else None,
        }
        for a in rows
    ]
