"""The commander's controls: one place to see the whole platform and act on it.

* Standing orders, in one city or every city: pause all bookings, pause one vehicle type (e.g.
  bike taxis during a strike) or switch surge off. They end by themselves (``ends_at``) or when
  lifted. Booking refuses with the order's reason; quotes show the ride type as unavailable.
* Every order and lift is written to the audit log and posted to #leadership and #operations,
  and drivers in the affected cities are told.
* A broadcast reaches staff, drivers and riders at once (an important announcement).
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BusinessRuleViolation

from .models import CommandOrder, OrderKind

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


def issue(
    *, user, kind: str, reason: str, city=None, vehicle_code: str = "", hours: int = 2, now=None
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
    order = CommandOrder.objects.create(
        kind=kind,
        city=city,
        vehicle_code=vehicle_code if kind == OrderKind.PAUSE_VEHICLE else "",
        reason=reason.strip()[:240],
        starts_at=now,
        ends_at=now + timedelta(hours=max(1, min(int(hours), 72))),
        created_by=user,
    )
    log_event(AuditAction.ACTION, order, message=f"Order: {order} ({order.reason})", actor=user)
    where = order.city.name if order.city else "every city"
    what = (
        f"pause {VEHICLES[order.vehicle_code].lower()}"
        if kind == OrderKind.PAUSE_VEHICLE
        else order.get_kind_display().lower()
    )
    _announce(
        f"🛑 Commander's order: {what} in {where} for {hours} h. Reason: {order.reason} "
        f"(by {user.get_full_name()})"
    )
    if kind != OrderKind.SURGE_OFF:
        _tell_drivers(order, f"{what.capitalize()} in {where}: {order.reason}")
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
        "history": [
            row(o, now)
            for o in CommandOrder.objects.select_related("city", "created_by", "lifted_by")[:20]
        ],
        "cities": cities,
        "vehicles": [{"code": k, "label": v} for k, v in VEHICLES.items()],
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
