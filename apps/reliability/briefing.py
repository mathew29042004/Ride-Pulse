"""The chief's inbox: the chief of staff keeps the chief (the commander) updated.

* Updates, briefings and escalations reach the chief live (``/ws/chat/``, the chief's own
  socket) wherever they are in the console, and as a notification; escalations are urgent.
* Decisions: the chief of staff asks the chief to decide. A request can carry a proposed order;
  approving it issues the order at once. The asker hears the answer live.
* The chief can reply to an update in one line; the sender is told.
* Auto-briefing: every 3 hours the chief of staff's briefing is drafted from live data (drivers,
  trips, open alerts, orders, incidents) and sent, so the chief is never in the dark.
* The chief is the commander, plus anyone acting commander right now.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation, InvalidStateTransition

from .models import ChiefUpdate, DecisionRequest, DecisionStatus, OrderKind, UpdateKind


def chiefs(*, now=None):
    from apps.accounts.models import Role, User

    from .models import Delegation

    now = now or timezone.now()
    acting = Delegation.objects.filter(starts_at__lte=now, ends_at__gt=now).values("to_id")
    return User.objects.filter(is_active=True).filter(Q(role=Role.COMMANDER) | Q(pk__in=acting))


def _push(users, event: str, data: dict) -> None:
    from apps.realtime import broadcast

    for u in users:
        broadcast.user_event(u.pk, event, data)


def _notify(users, title: str, body: str, *, urgent: bool, link: str) -> None:
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    for u in users:
        notify(u, title, body, level=Level.DANGER if urgent else Level.INFO, link=link)


# --- Updates ----------------------------------------------------------------------------------


def update_row(u: ChiefUpdate) -> dict:
    return {
        "id": u.pk,
        "kind": u.kind,
        "kind_label": u.get_kind_display(),
        "title": u.title,
        "body": u.body,
        "sent_by": u.sent_by.get_full_name(),
        "sent_at": u.sent_at.isoformat(),
        "read": u.read_at is not None,
        "reply": u.reply,
    }


@transaction.atomic
def send_update(*, user, title: str, body: str = "", kind: str = UpdateKind.UPDATE, now=None):
    now = now or timezone.now()
    if kind not in UpdateKind.values:
        raise BusinessRuleViolation("Choose update, briefing or escalation.", field="kind")
    if len(title.strip()) < 3:
        raise BusinessRuleViolation("Give it a title.", field="title")
    update = ChiefUpdate.objects.create(
        kind=kind, title=title.strip()[:160], body=body.strip()[:4000], sent_by=user, sent_at=now
    )
    to = list(chiefs(now=now))
    _push(to, "chief_update", update_row(update))
    urgent = kind == UpdateKind.ESCALATION
    _notify(
        to,
        f"{'🔴 Escalation' if urgent else update.get_kind_display()}: {update.title}",
        update.body[:200] or f"From {user.get_full_name()}",
        urgent=urgent,
        link="/ops/command",
    )
    return update


def reply(update: ChiefUpdate, *, user, text: str, now=None) -> ChiefUpdate:
    from apps.notifications.services import notify

    if not text.strip():
        raise BusinessRuleViolation("Write a reply.", field="text")
    update.reply = text.strip()[:500]
    update.read_at = update.read_at or now or timezone.now()
    update.save(update_fields=["reply", "read_at"])
    notify(
        update.sent_by,
        f"The chief replied: {update.title}",
        update.reply,
        link="/ops/brief",
    )
    _push([update.sent_by], "chief_reply", update_row(update))
    return update


def mark_read(user, *, now=None) -> int:
    return ChiefUpdate.objects.filter(read_at__isnull=True).update(read_at=now or timezone.now())


def draft_briefing(*, now=None) -> dict:
    """A briefing written from live data, for the chief of staff to send (or send itself)."""
    from . import command

    now = now or timezone.now()
    o = command.overview(now=now)
    live = o["live"]
    busiest = sorted(o["cities"], key=lambda c: -c["trips_today"])[:3]
    weak = [
        c
        for c in o["cities"]
        if c["completion_pct"] is not None and c["trips_today"] >= 30 and c["completion_pct"] < 60
    ]
    lines = [
        f"• {live['drivers_online'] + live['drivers_on_trip']} drivers live "
        f"({live['drivers_on_trip']} on a trip), {live['active_trips']} trips running, "
        f"{live['searching']} riders looking for a driver.",
        "• Busiest today: "
        + ", ".join(f"{c['name']} ({c['trips_today']} trips)" for c in busiest if c["trips_today"])
        + ".",
    ]
    if weak:
        lines.append(
            "• Watch: "
            + ", ".join(f"{c['name']} at {c['completion_pct']}% completed" for c in weak[:4])
            + "."
        )
    lines.append(
        f"• {len(o['alerts'])} open alerts, {len(o['open_incidents'])} open incidents, "
        f"{live['open_sos']} open SOS, {live['open_tickets']} support tickets open."
    )
    if o["orders"]:
        lines.append(
            "• Orders in force: "
            + "; ".join(f"{x['kind_label']} ({x['city']})" for x in o["orders"])
        )
    pending = DecisionRequest.objects.filter(status=DecisionStatus.PENDING).count()
    if pending:
        lines.append(f"• {pending} decisions waiting for you.")
    return {
        "title": f"Briefing, {timezone.localtime(now):%-d %b %-I:%M %p}",
        "body": "\n".join(lines),
    }


def auto_briefing(*, now=None) -> dict:
    """Every 3 hours (8 am to 10 pm): the chief of staff's briefing, drafted and sent."""
    from apps.accounts.models import Role, User

    now = now or timezone.now()
    if not 8 <= timezone.localtime(now).hour <= 22:
        return {"sent": 0}
    sender = User.objects.filter(role=Role.CHIEF_OF_STAFF, is_active=True).first()
    if sender is None:
        return {"sent": 0}
    recent = ChiefUpdate.objects.filter(
        kind=UpdateKind.BRIEFING, sent_by=sender, sent_at__gte=now - timedelta(hours=3)
    )
    if recent.exists():
        return {"sent": 0}
    draft = draft_briefing(now=now)
    send_update(user=sender, kind=UpdateKind.BRIEFING, now=now, **draft)
    return {"sent": 1}


def escalate_alert(alert_id: int, *, user, note: str = "", now=None) -> ChiefUpdate:
    from .models import CommandAlert

    alert = CommandAlert.objects.get(pk=alert_id)
    return send_update(
        user=user,
        kind=UpdateKind.ESCALATION,
        title=alert.title,
        body=(note.strip() + "\n\n" if note.strip() else "") + alert.detail,
        now=now,
    )


# --- Decisions --------------------------------------------------------------------------------


def decision_row(d: DecisionRequest) -> dict:
    from apps.geo.models import City

    from .command import VEHICLES

    order = d.order or {}
    city = City.objects.filter(pk=order.get("city")).first() if order.get("city") else None
    summary = ""
    if order:
        what = (
            f"Pause {VEHICLES.get(order.get('vehicle_code', ''), '').lower()}"
            if order.get("kind") == OrderKind.PAUSE_VEHICLE
            else OrderKind(order["kind"]).label
        )
        summary = f"{what} in {city.name if city else 'every city'} for {order.get('hours', 2)} h"
    return {
        "id": d.pk,
        "title": d.title,
        "detail": d.detail,
        "order": summary,
        "asked_by": d.asked_by.get_full_name(),
        "asked_at": d.asked_at.isoformat(),
        "status": d.status,
        "status_label": d.get_status_display(),
        "decided_by": d.decided_by.get_full_name() if d.decided_by else None,
        "note": d.note,
    }


def ask(*, user, title: str, detail: str = "", order: dict | None = None, now=None):
    now = now or timezone.now()
    if len(title.strip()) < 5:
        raise BusinessRuleViolation("Say what needs deciding.", field="title")
    clean = {}
    if order and order.get("kind"):
        if order["kind"] not in OrderKind.values:
            raise BusinessRuleViolation("Unknown order.", field="order")
        clean = {
            "kind": order["kind"],
            "city": int(order["city"]) if order.get("city") else None,
            "vehicle_code": order.get("vehicle_code", ""),
            "hours": max(1, min(int(order.get("hours", 2)), 72)),
            "reason": (order.get("reason") or title).strip()[:240],
        }
    d = DecisionRequest.objects.create(
        title=title.strip()[:160],
        detail=detail.strip()[:4000],
        order=clean,
        asked_by=user,
        asked_at=now,
    )
    to = list(chiefs(now=now))
    _push(to, "decision_request", decision_row(d))
    _notify(
        to,
        f"Decision needed: {d.title}",
        f"From {user.get_full_name()}"
        + (f". Proposes: {decision_row(d)['order']}" if clean else ""),
        urgent=True,
        link="/ops/command",
    )
    return d


@transaction.atomic
def decide(d: DecisionRequest, *, user, approve: bool, note: str = "", now=None):
    from apps.geo.models import City
    from apps.notifications.services import notify

    from . import command

    now = now or timezone.now()
    d = DecisionRequest.objects.select_for_update().get(pk=d.pk)
    if d.status != DecisionStatus.PENDING:
        raise InvalidStateTransition("This has already been decided.")
    if approve and d.order:
        o = d.order
        d.issued = command.issue(
            user=user,
            kind=o["kind"],
            reason=o["reason"],
            city=City.objects.filter(pk=o["city"]).first() if o.get("city") else None,
            vehicle_code=o.get("vehicle_code", ""),
            hours=o.get("hours", 2),
            confirm=True,  # the chief approving it is the confirmation
            now=now,
        )
    d.status = DecisionStatus.APPROVED if approve else DecisionStatus.DECLINED
    d.decided_by, d.decided_at, d.note = user, now, note.strip()[:500]
    d.save()
    verdict = "approved" if approve else "declined"
    notify(
        d.asked_by,
        f"The chief {verdict}: {d.title}",
        d.note or ("The order is in force." if approve and d.issued else ""),
        link="/ops/brief",
    )
    _push([d.asked_by], "decision_made", decision_row(d))
    return d


# --- Inboxes ----------------------------------------------------------------------------------


def chief_inbox() -> dict:
    return {
        "updates": [update_row(u) for u in ChiefUpdate.objects.select_related("sent_by")[:40]],
        "unread": ChiefUpdate.objects.filter(read_at__isnull=True).count(),
        "decisions": [
            decision_row(d)
            for d in DecisionRequest.objects.select_related("asked_by", "decided_by")[:30]
        ],
        "pending": DecisionRequest.objects.filter(status=DecisionStatus.PENDING).count(),
    }


def sender_view(user) -> dict:
    """What the chief of staff sees: their updates (and the chief's replies) and decisions."""
    from . import command

    overview = command.overview()
    return {
        "updates": [
            update_row(u)
            for u in ChiefUpdate.objects.filter(sent_by=user).select_related("sent_by")[:30]
        ],
        "decisions": [
            decision_row(d)
            for d in DecisionRequest.objects.filter(asked_by=user).select_related(
                "asked_by", "decided_by"
            )[:30]
        ],
        "draft": draft_briefing(),
        "alerts": overview["alerts"],
        "cities": [{"id": c["id"], "name": c["name"]} for c in overview["cities"]],
        "chiefs": [u.get_full_name() for u in chiefs()],
    }


def seed_chief_of_staff(*, log=print) -> dict:
    """The demo chief of staff, reporting to the commander, with a first briefing sent."""
    from apps.accounts.models import Department, Role, StaffProfile, User
    from apps.simulation.seed import DEMO_PASSWORD

    if User.objects.filter(email="chiefofstaff@ridepulse.dev").exists():
        return {"chief_of_staff": 0}
    user = User.objects.create_user(
        "chiefofstaff@ridepulse.dev",
        DEMO_PASSWORD,
        first_name="Ananya",
        last_name="Iyer",
        role=Role.CHIEF_OF_STAFF,
    )
    boss = StaffProfile.objects.filter(user__role=Role.COMMANDER).first()
    StaffProfile.objects.create(
        user=user,
        employee_id="RP-COS-001",
        title="Chief of Staff to the Commander",
        department=Department.LEADERSHIP,
        state="",
        reports_to=boss,
        joined_on=timezone.localdate() - timedelta(days=900),
    )
    from apps.chat.services import sync_channels

    sync_channels()
    if boss:
        draft = draft_briefing()
        send_update(user=user, kind=UpdateKind.BRIEFING, **draft)
        ask(
            user=user,
            title="Turn surge off in Chennai for the festival evening?",
            detail="Pongal crowds expected 6–10 pm. Riders complained about surge last year; "
            "a no-surge evening is good press and drivers get the festival quest instead.",
            order={
                "kind": "SURGE_OFF",
                "city": _city_id("chennai"),
                "hours": 4,
                "reason": "Festival evening: no surge in Chennai",
            },
        )
    log("  chief of staff: chiefofstaff@ridepulse.dev")
    return {"chief_of_staff": 1}


def _city_id(slug: str):
    from apps.geo.models import City

    return City.objects.filter(slug=slug).values_list("pk", flat=True).first()
