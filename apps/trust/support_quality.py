"""Support quality: CSAT after every resolved ticket, saved replies (macros) for agents, and a
help centre that answers common questions before anyone needs to raise a ticket.

* **CSAT:** when a ticket is resolved, the person who raised it is asked to rate the help 1-5.
  Scores roll up into each agent's scorecard and the support dashboard.
* **Macros:** saved replies with ``{name}``, ``{ticket}`` and ``{trip}`` filled in; usage is
  counted so the useful ones float to the top.
* **Help centre:** searchable articles for riders and drivers. "Was this helpful?" votes, and a
  deflection count: helpful, and no ticket from that person in the next hour.
"""

from datetime import datetime, timedelta

from django.db.models import Avg, Count, Exists, F, OuterRef, Q
from django.utils import timezone

from apps.core.exceptions import (
    ActionNotPermitted,
    BusinessRuleViolation,
    ConflictError,
    InvalidStateTransition,
)

from .models import Audience, HelpArticle, HelpVote, Macro, TicketRating

DEFLECTION_WINDOW = timedelta(hours=1)


# --- CSAT ------------------------------------------------------------------------------------


def rate(
    ticket, *, user, score: int, comment: str = "", now: datetime | None = None
) -> TicketRating:
    if ticket.raised_by_id != user.pk:
        raise ActionNotPermitted("Only the person who raised the ticket can rate it.")
    if ticket.status not in ("RESOLVED", "CLOSED"):
        raise InvalidStateTransition("You can rate the help once the ticket is resolved.")
    if not 1 <= int(score) <= 5:
        raise BusinessRuleViolation("Score 1 to 5.", field="score")
    if TicketRating.objects.filter(ticket=ticket).exists():
        raise ConflictError("You've already rated this ticket.")
    return TicketRating.objects.create(
        ticket=ticket,
        score=int(score),
        comment=comment.strip()[:500],
        agent=ticket.assigned_to,
        created_at=now or timezone.now(),
    )


def csat_by_agent(agent_ids, since: datetime) -> dict[int, dict]:
    rows = (
        TicketRating.objects.filter(agent_id__in=agent_ids, created_at__gte=since)
        .values("agent_id")
        .annotate(avg=Avg("score"), n=Count("pk"), happy=Count("pk", filter=Q(score__gte=4)))
    )
    return {
        r["agent_id"]: {
            "avg": round(r["avg"], 2),
            "n": r["n"],
            "csat": round(100 * r["happy"] / r["n"]),
        }
        for r in rows
    }


def csat_summary(*, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    ratings = TicketRating.objects.filter(created_at__gte=since)
    agg = ratings.aggregate(
        avg=Avg("score"), n=Count("pk"), happy=Count("pk", filter=Q(score__gte=4))
    )
    by_category = list(
        ratings.values("ticket__category").annotate(avg=Avg("score"), n=Count("pk")).order_by("avg")
    )
    return {
        "days": days,
        "ratings": agg["n"],
        "average": round(agg["avg"], 2) if agg["avg"] else None,
        # CSAT the way most teams report it: share of 4 and 5 star answers.
        "csat_percent": round(100 * agg["happy"] / agg["n"]) if agg["n"] else None,
        "by_category": [
            {"category": r["ticket__category"], "average": round(r["avg"], 2), "ratings": r["n"]}
            for r in by_category
        ],
        "recent_comments": list(
            ratings.exclude(comment="")
            .order_by("-created_at")
            .values("score", "comment", "ticket__ticket_number")[:8]
        ),
    }


# --- Macros ----------------------------------------------------------------------------------


def render_macro(macro: Macro, ticket) -> str:
    name = ticket.raised_by.first_name if ticket.raised_by else "there"
    return (
        macro.body.replace("{name}", name or "there")
        .replace("{ticket}", ticket.ticket_number)
        .replace("{trip}", ticket.trip.trip_number if ticket.trip_id else "your trip")
    )


def use_macro(macro: Macro, ticket, *, agent, internal: bool = False):
    from apps.support.services import reply

    if not macro.is_active:
        raise BusinessRuleViolation("This saved reply is switched off.")
    message = reply(ticket, author=agent, body=render_macro(macro, ticket), internal=internal)
    Macro.objects.filter(pk=macro.pk).update(uses=F("uses") + 1)
    return message


def macros_for(category: str = ""):
    macros = Macro.objects.filter(is_active=True)
    if category:
        macros = macros.filter(Q(category=category) | Q(category=""))
    return macros


# --- Help centre -----------------------------------------------------------------------------


def search(query: str = "", *, audience: str = Audience.RIDER, category: str = "", limit: int = 20):
    """Riders and drivers see theirs and everyone's; staff see only the internal handbook."""
    audiences = [Audience.STAFF] if audience == Audience.STAFF else [audience, Audience.ALL]
    articles = HelpArticle.objects.filter(is_published=True, audience__in=audiences)
    if category:
        articles = articles.filter(category__iexact=category)
    words = [w for w in query.lower().split() if len(w) > 2][:6]
    for word in words:
        articles = articles.filter(
            Q(title__icontains=word) | Q(keywords__icontains=word) | Q(body__icontains=word)
        )
    return articles.order_by("-views", "title")[:limit]


def view(article: HelpArticle) -> HelpArticle:
    HelpArticle.objects.filter(pk=article.pk).update(views=F("views") + 1)
    return article


def vote(article: HelpArticle, *, user, helpful: bool, now: datetime | None = None) -> HelpVote:
    vote, _ = HelpVote.objects.update_or_create(
        article=article,
        user=user,
        defaults={"helpful": helpful, "created_at": now or timezone.now()},
    )
    return vote


def _deflected_votes(votes):
    """Helpful votes with no ticket from the same person within the following hour."""
    from apps.support.models import SupportTicket

    ticket_soon = SupportTicket.objects.filter(
        raised_by=OuterRef("user"),
        created_at__gte=OuterRef("created_at"),
        created_at__lt=OuterRef("created_at") + DEFLECTION_WINDOW,
    )
    return votes.filter(helpful=True, created_at__lt=timezone.now() - DEFLECTION_WINDOW).exclude(
        Exists(ticket_soon)
    )


def help_stats() -> dict:
    articles = HelpArticle.objects.filter(is_published=True)
    votes = HelpVote.objects.all()
    helpful = votes.filter(helpful=True).count()
    total = votes.count()
    per_article = (
        articles.annotate(
            up=Count("votes", filter=Q(votes__helpful=True)),
            down=Count("votes", filter=Q(votes__helpful=False)),
        )
        .filter(down__gt=F("up"))
        .values("slug", "title", "up", "down")[:5]
    )
    return {
        "articles": articles.count(),
        "views": sum(articles.values_list("views", flat=True)),
        "helpful_percent": round(100 * helpful / total) if total else None,
        "deflections": _deflected_votes(votes).count(),
        "needs_work": list(per_article),
    }
