"""The commander's controls: one place to see the whole platform and act on it.

* Standing orders, in one city or every city: pause all bookings, pause one vehicle type (e.g.
  bike taxis during a strike) or switch surge off. They end by themselves (``ends_at``) or when
  lifted. Booking refuses with the order's reason; quotes show the ride type as unavailable.
* Every order and lift is written to the audit log and posted to #leadership and #operations,
  and drivers in the affected cities are told.
* A broadcast reaches staff, drivers and riders at once (an important announcement).
* The watchtower (every minute) raises live alerts: riders stranded with no drivers nearby,
  completion collapsing in a city, an SOS nobody has picked up. They appear in the command centre
  at once (over the ops socket) and the commander and administrators are notified.
* People: find anyone by phone, email, name or trip number and act (suspend or reinstate a
  driver, block or unblock a rider, take a driver offline, cancel a stuck trip).
* Delegation: the commander can make an administrator or regional manager acting commander for
  a few hours; it ends by itself or when revoked.
* Pausing bookings in every city is the one order that must be confirmed.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

from .models import CommandAlert, CommandOrder, Delegation, OrderKind

VEHICLES = {"BIKE": "Bike taxis", "AUTO": "Autos", "CAR": "Cars"}


def active(city=None, *, now=None):
    now = now or timezone.now()
    orders = CommandOrder.objects.filter(starts_at__lte=now, ends_at__gt=now)
    if city is not None:
        orders = orders.filter(Q(city=city) | Q(city__isnull=True))
    return orders


def refusal(city, vehicle_code: str, *, now=None) -> str | None:
    """Why a booking of this vehicle in this city is refused right now, or None."""
    for order in active(city, now=now).exclude(kind=OrderKind.SURGE_OFF):
        if order.kind == OrderKind.PAUSE_BOOKINGS or order.vehicle_code == vehicle_code:
            what = (
                "Bookings are"
                if order.kind == OrderKind.PAUSE_BOOKINGS
                else f"{VEHICLES.get(order.vehicle_code, order.vehicle_code)} are"
            )
            return f"{what} paused right now: {order.reason}"
    return None


def surge_cap(city, *, now=None) -> Decimal | None:
    return Decimal(1) if active(city, now=now).filter(kind=OrderKind.SURGE_OFF).exists() else None


def _announce(text: str) -> None:
    from apps.chat.models import Conversation, Message
    from apps.chat.services import _deliver

    now = timezone.now()
    for channel in Conversation.objects.filter(
        kind="CHANNEL", slug__in=["leadership", "operations"]
    ):
        message = Message.objects.create(conversation=channel, body=text, created_at=now)
        Conversation.objects.filter(pk=channel.pk).update(last_message_at=now)
        _deliver(channel, message)


def _tell_drivers(order: CommandOrder, text: str) -> None:
    from apps.drivers.models import DriverProfile
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    drivers = DriverProfile.objects.filter(availability__in=["ONLINE", "ON_TRIP"])
    if order.city_id:
        drivers = drivers.filter(city_id=order.city_id)
    for d in drivers.select_related("user")[:500]:
        notify(d.user, "Message from Ride Pulse", text, level=Level.WARNING, link="/drive")


def _live(event: str, data: dict) -> None:
    from apps.realtime import broadcast

    broadcast.ops_event(event, data)


def issue(
    *,
    user,
    kind: str,
    reason: str,
    city=None,
    vehicle_code: str = "",
    hours: int = 2,
    confirm: bool = False,
    starts_at=None,
    now=None,
) -> CommandOrder:
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    now = now or timezone.now()
    if kind not in OrderKind.values:
        raise BusinessRuleViolation("Choose an order.", field="kind")
    if kind == OrderKind.PAUSE_VEHICLE and vehicle_code not in VEHICLES:
        raise BusinessRuleViolation("Choose the vehicle type to pause.", field="vehicle_code")
    if len(reason.strip()) < 10:
        raise BusinessRuleViolation(
            "Give the reason: riders and drivers will see it.", field="reason"
        )
    start = max(starts_at or now, now)
    if start > now + timedelta(days=30):
        raise BusinessRuleViolation("Schedule orders up to 30 days ahead.", field="starts_at")
    if kind == OrderKind.PAUSE_BOOKINGS and city is None and not confirm:
        raise BusinessRuleViolation(
            "Pausing bookings in every city stops the whole platform. Confirm to go ahead.",
            field="confirm",
        )
    order = CommandOrder.objects.create(
        kind=kind,
        city=city,
        vehicle_code=vehicle_code if kind == OrderKind.PAUSE_VEHICLE else "",
        reason=reason.strip()[:240],
        starts_at=start,
        ends_at=start + timedelta(hours=max(1, min(int(hours), 72))),
        created_by=user,
    )
    log_event(AuditAction.ACTION, order, message=f"Order: {order} ({order.reason})", actor=user)
    where = order.city.name if order.city else "every city"
    what = (
        f"pause {VEHICLES[order.vehicle_code].lower()}"
        if kind == OrderKind.PAUSE_VEHICLE
        else order.get_kind_display().lower()
    )
    when = (
        f" from {timezone.localtime(start):%-d %b, %-I:%M %p}"
        if start > now + timedelta(minutes=1)
        else ""
    )
    _announce(
        f"🛑 Commander's order: {what} in {where}{when} for {hours} h. Reason: {order.reason} "
        f"(by {user.get_full_name()})"
    )
    if kind != OrderKind.SURGE_OFF:
        _tell_drivers(order, f"{what.capitalize()} in {where}: {order.reason}")
    _live("command_order", row(order, now))
    return order


def lift(order: CommandOrder, *, user, now=None) -> CommandOrder:
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    now = now or timezone.now()
    if order.ends_at <= now:
        raise BusinessRuleViolation("That order has already ended.")
    order.ends_at, order.lifted_by = now, user
    order.save(update_fields=["ends_at", "lifted_by"])
    log_event(AuditAction.ACTION, order, message=f"Lifted: {order}", actor=user)
    _announce(f"✅ Order lifted: {order} (by {user.get_full_name()})")
    _live("command_order", row(order, now))
    return order


def broadcast(*, user, title: str, body: str, audiences: list[str], now=None) -> int:
    """One message to staff, drivers and/or riders, as an important announcement."""
    from apps.announcements import services as announcements

    audiences = [a for a in audiences if a in ("STAFF", "DRIVERS", "RIDERS")]
    if not audiences:
        raise BusinessRuleViolation("Choose who hears it.", field="audiences")
    for audience in audiences:
        announcements.publish(
            user=user,
            audience=audience,
            text={"en": {"title": title, "body": body}},
            important=True,
            now=now,
        )
    _announce(f"📣 Commander's broadcast to {', '.join(a.lower() for a in audiences)}: {title}")
    return len(audiences)


def row(o: CommandOrder, now=None) -> dict:
    now = now or timezone.now()
    return {
        "id": o.pk,
        "kind": o.kind,
        "kind_label": o.get_kind_display(),
        "city": o.city.name if o.city else "All cities",
        "vehicle": VEHICLES.get(o.vehicle_code, ""),
        "reason": o.reason,
        "starts_at": o.starts_at.isoformat(),
        "ends_at": o.ends_at.isoformat(),
        "active": o.starts_at <= now < o.ends_at,
        "scheduled": o.starts_at > now,
        "by": o.created_by.get_full_name() if o.created_by else None,
        "lifted_by": o.lifted_by.get_full_name() if o.lifted_by else None,
    }


def overview(*, now=None) -> dict:
    """Every city at a glance, with what's wrong in each, plus the orders in force."""
    from django.db.models import Count

    from apps.analytics.services import live_status
    from apps.drivers.models import DriverProfile
    from apps.geo.models import City
    from apps.rides.models import Trip, TripStatus

    from . import weather
    from .models import Incident, IncidentStatus

    now = now or timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    drivers = dict(
        DriverProfile.objects.filter(availability__in=["ONLINE", "ON_TRIP"])
        .values_list("city_id")
        .annotate(n=Count("id"))
    )
    trips = {
        r["city_id"]: r
        for r in Trip.objects.filter(requested_at__gte=today)
        .values("city_id")
        .annotate(
            n=Count("id"),
            done=Count("id", filter=Q(status=TripStatus.COMPLETED)),
            searching=Count("id", filter=Q(status=TripStatus.REQUESTED)),
        )
    }
    orders = list(active(now=now).select_related("city", "created_by", "lifted_by"))
    open_incidents = Incident.objects.exclude(status=IncidentStatus.RESOLVED)
    cities = []
    for c in City.objects.filter(is_active=True).order_by("state", "name"):
        t = trips.get(c.pk, {"n": 0, "done": 0, "searching": 0})
        alert = weather.active(c, now=now)
        city_orders = [o for o in orders if o.city_id in (None, c.pk)]
        flags = [o.get_kind_display() for o in city_orders]
        if alert:
            flags.append(alert.get_level_display())
        cities.append(
            {
                "id": c.pk,
                "name": c.name,
                "state": c.state,
                "drivers_live": drivers.get(c.pk, 0),
                "trips_today": t["n"],
                "completion_pct": round(100 * t["done"] / t["n"]) if t["n"] else None,
                "searching": t["searching"],
                "flags": flags,
                "health": "red"
                if any(o.kind == OrderKind.PAUSE_BOOKINGS for o in city_orders)
                else "amber"
                if flags
                else "green",
            }
        )
    return {
        "live": live_status(),
        "open_incidents": [
            {"id": i.pk, "number": i.number, "title": i.title, "severity": i.severity}
            for i in open_incidents[:10]
        ],
        "orders": [row(o, now) for o in orders],
        "scheduled": [
            row(o, now)
            for o in CommandOrder.objects.filter(starts_at__gt=now).select_related(
                "city", "created_by"
            )
        ],
        "leaders": leaderboard(now=now),
        "history": [
            row(o, now)
            for o in CommandOrder.objects.select_related("city", "created_by", "lifted_by")[:20]
        ],
        "cities": cities,
        "vehicles": [{"code": k, "label": v} for k, v in VEHICLES.items()],
        "alerts": [
            alert_row(a)
            for a in CommandAlert.objects.filter(acknowledged_at__isnull=True).select_related(
                "city"
            )[:30]
        ],
        "delegations": [
            delegation_row(d, now)
            for d in Delegation.objects.filter(ends_at__gt=now).select_related("to")
        ],
        "candidates": candidates(),
    }


def seed_commander(*, log=print) -> dict:
    """The demo commander, at the top of the org chart (the administrator reports to them), and
    a member of every team channel."""
    from apps.accounts.models import Department, Role, StaffProfile, User
    from apps.simulation.seed import DEMO_PASSWORD

    if User.objects.filter(email="commander@ridepulse.dev").exists():
        return {"commander": 0}
    user = User.objects.create_user(
        "commander@ridepulse.dev",
        DEMO_PASSWORD,
        first_name="Vikram",
        last_name="Rao",
        role=Role.COMMANDER,
    )
    profile = StaffProfile.objects.create(
        user=user,
        employee_id="RP-CMD-001",
        title="Commander · Chief Executive",
        department=Department.LEADERSHIP,
        state="",
        joined_on=timezone.localdate() - timedelta(days=2000),
    )
    StaffProfile.objects.filter(user__role=Role.ADMIN, reports_to__isnull=True).update(
        reports_to=profile
    )
    from apps.chat.services import sync_channels

    sync_channels()
    log("  commander: commander@ridepulse.dev")
    return {"commander": 1}


# --- Delegation ---------------------------------------------------------------------------------


def is_acting_commander(user, *, now=None) -> bool:
    now = now or timezone.now()
    return Delegation.objects.filter(to=user, starts_at__lte=now, ends_at__gt=now).exists()


def delegate(*, user, to, hours: int, reason: str, now=None) -> Delegation:
    from apps.accounts.models import STAFF_ROLES_FOR_DELEGATION
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    now = now or timezone.now()
    if user.role != "COMMANDER":
        raise BusinessRuleViolation("Only the commander can hand over command.")
    if to.role not in STAFF_ROLES_FOR_DELEGATION or not to.is_active:
        raise BusinessRuleViolation(
            "Hand over only to an administrator or a regional manager.", field="to"
        )
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation("Say why (e.g. travelling).", field="reason")
    Delegation.objects.filter(to=to, ends_at__gt=now).update(ends_at=now)
    d = Delegation.objects.create(
        to=to,
        by=user,
        reason=reason.strip()[:240],
        starts_at=now,
        ends_at=now + timedelta(hours=max(1, min(int(hours), 72))),
    )
    log_event(AuditAction.ACTION, d, message=f"Command handed to {to} ({d.reason})", actor=user)
    notify(
        to,
        "You're acting commander",
        f"{user.get_full_name()} handed you command for {hours} h: {d.reason}. "
        "The command centre is in your menu.",
        level=Level.WARNING,
        link="/ops/command",
    )
    _announce(f"👑 {to.get_full_name()} is acting commander for {hours} h ({d.reason}).")
    return d


def revoke(d: Delegation, *, user, now=None) -> Delegation:
    from apps.audit.models import AuditAction
    from apps.audit.services import log_event

    now = now or timezone.now()
    if user.role != "COMMANDER":
        raise BusinessRuleViolation("Only the commander can take command back.")
    d.ends_at = min(d.ends_at, now)
    d.save(update_fields=["ends_at"])
    log_event(AuditAction.ACTION, d, message=f"Command taken back from {d.to}", actor=user)
    _announce(f"👑 Command is back with {user.get_full_name()}.")
    return d


def delegation_row(d: Delegation, now=None) -> dict:
    now = now or timezone.now()
    return {
        "id": d.pk,
        "to": d.to.get_full_name(),
        "to_role": d.to.get_role_display(),
        "reason": d.reason,
        "ends_at": d.ends_at.isoformat(),
        "active": d.starts_at <= now < d.ends_at,
    }


def candidates() -> list[dict]:
    from apps.accounts.models import STAFF_ROLES_FOR_DELEGATION, User

    return [
        {"id": u.pk, "name": u.get_full_name(), "role": u.get_role_display()}
        for u in User.objects.filter(role__in=STAFF_ROLES_FOR_DELEGATION, is_active=True).order_by(
            "role", "first_name"
        )
    ]


# --- Watchtower ----------------------------------------------------------------------------------

STRANDED = 5  # riders waiting for a driver in one city
COMPLETION_FLOOR = 50  # % of today's trips, once a city has at least MIN_TRIPS
MIN_TRIPS = 30
SOS_UNPICKED = timedelta(minutes=3)


def _raise(key: str, *, level: str, title: str, detail: str, city=None, link: str = "", now):
    """One open alert per key; returns the new alert or None when it's already open."""
    if CommandAlert.objects.filter(key=key, acknowledged_at__isnull=True).exists():
        return None
    if CommandAlert.objects.filter(key=key, raised_at__gte=now - timedelta(minutes=30)).exists():
        return None  # acknowledged in the last half hour: don't nag
    alert = CommandAlert.objects.create(
        key=key, level=level, title=title, detail=detail, city=city, link=link, raised_at=now
    )
    from apps.accounts.models import User
    from apps.notifications.models import Level
    from apps.notifications.services import notify

    for u in User.objects.filter(role__in=["COMMANDER", "ADMIN"], is_active=True):
        notify(
            u,
            title,
            detail,
            level=Level.DANGER if level == "CRITICAL" else Level.WARNING,
            link="/ops/command",
        )
    _live("command_alert", alert_row(alert))
    return alert


def watch(*, now=None) -> dict:
    """Every minute: look for trouble in each city and raise alerts."""
    from django.db.models import Count

    from apps.geo.models import City
    from apps.rides.models import Trip, TripStatus
    from apps.support.models import IncidentStatus as SosStatus
    from apps.support.models import SafetyIncident

    now = now or timezone.now()
    raised = 0
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    waiting = dict(
        Trip.objects.filter(
            status=TripStatus.REQUESTED, requested_at__gte=now - timedelta(minutes=15)
        )
        .values_list("city_id")
        .annotate(n=Count("id"))
    )
    stats = {
        r["city_id"]: r
        for r in Trip.objects.filter(requested_at__gte=today)
        .values("city_id")
        .annotate(n=Count("id"), done=Count("id", filter=Q(status=TripStatus.COMPLETED)))
    }
    for city in City.objects.filter(is_active=True):
        n = waiting.get(city.pk, 0)
        if n >= STRANDED:
            raised += bool(
                _raise(
                    f"stranded:{city.pk}",
                    level="CRITICAL" if n >= 2 * STRANDED else "WARNING",
                    title=f"{n} riders waiting for a driver in {city.name}",
                    detail="Consider a surge, a driver quest or a broadcast to drivers nearby.",
                    city=city,
                    link="/ops/live",
                    now=now,
                )
            )
        s = stats.get(city.pk)
        if s and s["n"] >= MIN_TRIPS and 100 * s["done"] / s["n"] < COMPLETION_FLOOR:
            pct = round(100 * s["done"] / s["n"])
            raised += bool(
                _raise(
                    f"completion:{city.pk}:{today:%Y%m%d}",
                    level="WARNING",
                    title=f"Only {pct}% of trips completed in {city.name} today",
                    detail=f"{s['done']} of {s['n']} trips. Check cancellations and driver supply.",
                    city=city,
                    link="/ops/analytics",
                    now=now,
                )
            )
    for sos in SafetyIncident.objects.filter(
        status=SosStatus.OPEN, created_at__lte=now - SOS_UNPICKED
    ).select_related("trip__city")[:20]:
        raised += bool(
            _raise(
                f"sos:{sos.pk}",
                level="CRITICAL",
                title=f"SOS {sos.incident_number} not picked up",
                detail=f"Raised {int((now - sos.created_at).total_seconds() // 60)} minutes ago "
                f"in {sos.trip.city.name}. Nobody has acknowledged it.",
                city=sos.trip.city,
                link=f"/ops/safety/{sos.pk}",
                now=now,
            )
        )
    return {"alerts_raised": raised}


def alert_row(a: CommandAlert) -> dict:
    return {
        "id": a.pk,
        "level": a.level,
        "title": a.title,
        "detail": a.detail,
        "city": a.city.name if a.city else None,
        "link": a.link,
        "raised_at": a.raised_at.isoformat(),
        "acknowledged_by": a.acknowledged_by.get_full_name() if a.acknowledged_by else None,
    }


def acknowledge(alert: CommandAlert, *, user, now=None) -> CommandAlert:
    alert.acknowledged_by, alert.acknowledged_at = user, now or timezone.now()
    alert.save(update_fields=["acknowledged_by", "acknowledged_at"])
    _live("command_alert", alert_row(alert))
    return alert


# --- People ---------------------------------------------------------------------------------


def find_people(q: str) -> list[dict]:
    """Drivers, riders and trips matching a phone, email, name or trip number."""
    from apps.drivers.models import DriverProfile
    from apps.riders.models import RiderProfile
    from apps.rides.models import Trip

    q = q.strip()
    if len(q) < 3:
        return []
    people = Q(user__email__icontains=q) | Q(user__phone__icontains=q)
    parts = q.split()
    if len(parts) > 1:
        people |= Q(user__first_name__icontains=parts[0], user__last_name__icontains=parts[-1])
    else:
        people |= Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
    out = []
    for d in DriverProfile.objects.filter(people).select_related("user", "city")[:6]:
        out.append(
            {
                "kind": "driver",
                "id": d.pk,
                "name": d.user.get_full_name(),
                "detail": f"Driver · {d.city.name} · {d.get_availability_display()}",
                "status": d.onboarding_status,
                "suspended": d.onboarding_status == "SUSPENDED",
                "online": d.availability != "OFFLINE",
                "link": f"/ops/drivers/{d.pk}",
            }
        )
    for r in RiderProfile.objects.filter(people).select_related("user")[:6]:
        out.append(
            {
                "kind": "rider",
                "id": r.pk,
                "name": r.user.get_full_name(),
                "detail": f"Rider · {r.user.email}",
                "blocked": r.is_blocked,
                "link": f"/ops/riders/{r.pk}",
            }
        )
    for t in Trip.objects.filter(trip_number__icontains=q).select_related("city")[:4]:
        out.append(
            {
                "kind": "trip",
                "id": t.pk,
                "name": t.trip_number,
                "detail": f"Trip · {t.city.name} · {t.get_status_display()}",
                "status": t.status,
                "link": f"/ops/trips/{t.pk}",
            }
        )
    return out


def act(*, user, kind: str, id: int, action: str, reason: str = "") -> dict:
    """One action on a driver, rider or trip, with a reason, audited by the services it calls."""
    from apps.drivers import services as drivers
    from apps.drivers.models import DriverProfile
    from apps.riders import services as riders
    from apps.riders.models import RiderProfile
    from apps.rides import services as rides
    from apps.rides.models import Trip

    if action != "offline" and len(reason.strip()) < 5:
        raise BusinessRuleViolation("Give a reason.", field="reason")
    if kind == "driver":
        driver = DriverProfile.objects.get(pk=id)
        if action == "suspend":
            drivers.suspend_driver(driver, reason=reason, actor=user)
        elif action == "reinstate":
            drivers.reinstate_driver(driver, actor=user)
        elif action == "offline":
            drivers.go_offline(driver)
        else:
            raise BusinessRuleViolation("Unknown action.")
    elif kind == "rider":
        rider = RiderProfile.objects.get(pk=id)
        if action not in ("block", "unblock"):
            raise BusinessRuleViolation("Unknown action.")
        riders.set_blocked(rider, action == "block", reason=reason, actor=user)
    elif kind == "trip" and action == "cancel":
        rides.cancel_trip(Trip.objects.get(pk=id), user=user, reason=reason)
    else:
        raise BusinessRuleViolation("Unknown action.")
    _live("command_action", {"kind": kind, "id": id, "action": action, "by": user.get_full_name()})
    return {"done": True}


# --- Leaderboards and thanks ----------------------------------------------------------------------


def leaderboard(*, now=None) -> dict:
    """This week's best city (completion), support agent (tickets resolved) and driver."""
    from django.db.models import Count, Q

    from apps.drivers.models import DriverProfile
    from apps.rides.models import Trip, TripStatus
    from apps.support.models import SupportTicket

    now = now or timezone.now()
    since = now - timedelta(days=7)
    cities = (
        Trip.objects.filter(requested_at__gte=since)
        .values("city_id", "city__name")
        .annotate(n=Count("id"), done=Count("id", filter=Q(status=TripStatus.COMPLETED)))
        .filter(n__gte=20)
    )
    best_city = max(cities, key=lambda c: c["done"] / c["n"], default=None)
    agent = (
        SupportTicket.objects.filter(resolved_at__gte=since, assigned_to__isnull=False)
        .values("assigned_to_id", "assigned_to__first_name", "assigned_to__last_name")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )
    driver = (
        Trip.objects.filter(status=TripStatus.COMPLETED, completed_at__gte=since)
        .values("driver_id")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )
    d = (
        DriverProfile.objects.select_related("user", "city")
        .filter(pk=driver["driver_id"] if driver else None)
        .first()
    )
    return {
        "city": {
            "id": best_city["city_id"],
            "name": best_city["city__name"],
            "detail": f"{round(100 * best_city['done'] / best_city['n'])}% of "
            f"{best_city['n']} trips completed",
        }
        if best_city
        else None,
        "agent": {
            "user_id": agent["assigned_to_id"],
            "name": f"{agent['assigned_to__first_name']} {agent['assigned_to__last_name']}",
            "detail": f"{agent['n']} tickets resolved",
        }
        if agent
        else None,
        "driver": {
            "user_id": d.user_id,
            "name": d.name,
            "detail": f"{driver['n']} trips in {d.city.name} · ★ {d.rating}",
        }
        if d
        else None,
    }


def thank(*, user, kind: str, note: str = "", now=None) -> str:
    """The chief thanks this week's winner: they're told, and it's posted to #general."""
    from apps.accounts.models import StaffProfile, User
    from apps.chat.models import Conversation, Message
    from apps.chat.services import _deliver
    from apps.notifications.services import notify

    now = now or timezone.now()
    board = leaderboard(now=now)
    winner = board.get(kind)
    if not winner:
        raise BusinessRuleViolation("Nobody to thank there yet this week.")
    text = note.strip() or "Outstanding work this week. Thank you!"
    line = f"🏆 {user.get_full_name()} thanks {winner['name']} ({winner['detail']}): {text}"
    if kind == "city":
        people = User.objects.filter(
            pk__in=StaffProfile.objects.filter(city_id=winner["id"]).values("user_id")
        )
    else:
        people = User.objects.filter(pk=winner["user_id"])
    for p in people[:200]:
        notify(p, "🏆 A thank-you from the chief", line)
    general = Conversation.objects.filter(kind="CHANNEL", slug="general").first()
    if general:
        message = Message.objects.create(conversation=general, body=line, created_at=now)
        Conversation.objects.filter(pk=general.pk).update(last_message_at=now)
        _deliver(general, message)
    return line
