"""Profit and loss by city and month.

* **From the ledger** (exact): commission and booking fees earned, promotion spend (discounts,
  bonuses, incentives, referrals), refunds. Each transaction counts for the city of its trip;
  money with no trip behind it (Ride Pass sales, some bonuses) is shown on its own line, never
  guessed into a city.
* **Estimates** (labelled, from ``settings.PNL_ASSUMPTIONS``): card gateway fees (UPI has no
  merchant fee in India) and the cost of handling support tickets.
* **GST** collected is shown separately: it belongs to the government, not to revenue.

The bottom line is a **contribution** (before salaries, marketing, offices and technology),
not a full profit: those company-wide costs aren't in the ledger.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.payments import accounts

ZERO = Decimal(0)
DEFAULTS = {"card_fee_percent": Decimal("2.0"), "cost_per_ticket": Decimal("45")}


def assumptions() -> dict:
    return {**DEFAULTS, **getattr(settings, "PNL_ASSUMPTIONS", {})}


def month_bounds(month: date):
    from datetime import datetime, time

    start = timezone.make_aware(datetime.combine(month.replace(day=1), time()))
    nxt = (month.replace(day=28) + __import__("datetime").timedelta(days=4)).replace(day=1)
    return start, timezone.make_aware(datetime.combine(nxt, time()))


def _ledger(start, end):
    """Signed sums per (city, account) for the platform's accounts. Earnings accounts
    (commission, fees, subscriptions, GST) are positive when money comes in; spending accounts
    (promotions, refunds) go negative, so the report flips those to show costs as positive."""
    from apps.payments.models import LedgerEntry

    rows = (
        LedgerEntry.objects.filter(
            transaction__created_at__gte=start,
            transaction__created_at__lt=end,
            wallet__isnull=True,
            account__in=[
                accounts.PLATFORM_COMMISSION,
                accounts.PLATFORM_FEES,
                accounts.PLATFORM_PROMOTIONS,
                accounts.PLATFORM_REFUNDS,
                accounts.PLATFORM_SUBSCRIPTIONS,
                accounts.GST_PAYABLE,
            ],
        )
        .values("transaction__trip__city_id", "account")
        .annotate(total=Sum("amount"))
    )
    out: dict = {}
    for r in rows:
        out.setdefault(r["transaction__trip__city_id"], {})[r["account"]] = r["total"] or ZERO
    return out


def report(month: date) -> dict:
    from apps.geo.models import City
    from apps.rides.models import Trip, TripStatus
    from apps.support.models import SupportTicket

    from .models import CityBudget

    start, end = month_bounds(month)
    rules = assumptions()
    ledger = _ledger(start, end)
    trips = {
        r["city_id"]: r
        for r in Trip.objects.filter(
            status=TripStatus.COMPLETED, completed_at__gte=start, completed_at__lt=end
        )
        .values("city_id")
        .annotate(
            n=Count("pk"),
            gmv=Sum("fare_total"),
            card=Sum("fare_total", filter=Q(payment_method="CARD")),
        )
    }
    tickets = dict(
        SupportTicket.objects.filter(created_at__gte=start, created_at__lt=end, trip__isnull=False)
        .values_list("trip__city_id")
        .annotate(n=Count("pk"))
        .values_list("trip__city_id", "n")
    )
    budgets = {b.city_id: b for b in CityBudget.objects.filter(month=start.date())}

    def line(city_id) -> dict:
        money = ledger.get(city_id, {})
        commission = money.get(accounts.PLATFORM_COMMISSION, ZERO)
        fees = money.get(accounts.PLATFORM_FEES, ZERO)
        subscriptions = money.get(accounts.PLATFORM_SUBSCRIPTIONS, ZERO)
        promotions = -money.get(accounts.PLATFORM_PROMOTIONS, ZERO)
        refunds = -money.get(accounts.PLATFORM_REFUNDS, ZERO)
        t = trips.get(city_id, {})
        card_fees = (Decimal(t.get("card") or 0) * rules["card_fee_percent"] / 100).quantize(
            Decimal("0.01")
        )
        support = Decimal(tickets.get(city_id, 0)) * rules["cost_per_ticket"]
        revenue = commission + fees + subscriptions
        costs = promotions + refunds + card_fees + support
        row = {
            "trips": t.get("n", 0),
            "gmv": str(Decimal(t.get("gmv") or 0)),
            "commission": str(commission),
            "fees": str(fees),
            "subscriptions": str(subscriptions),
            "revenue": str(revenue),
            "promotions": str(promotions),
            "refunds": str(refunds),
            "card_fees_est": str(card_fees),
            "support_est": str(support),
            "costs": str(costs),
            "contribution": str(revenue - costs),
            "margin": round(float((revenue - costs) / revenue), 3) if revenue else None,
            "gst_collected": str(money.get(accounts.GST_PAYABLE, ZERO)),
        }
        budget = budgets.get(city_id)
        if budget:
            row["budget"] = {
                "revenue": str(budget.revenue),
                "promotions": str(budget.promotions),
                "revenue_vs_budget": round(float(revenue / budget.revenue) - 1, 3)
                if budget.revenue
                else None,
                "promotions_over": promotions > budget.promotions,
            }
        return row

    cities = City.objects.filter(pk__in=[c for c in ledger if c] + list(trips)).order_by("name")
    rows = [
        {"city_id": c.pk, "slug": c.slug, "city": c.name, "state": c.state, **line(c.pk)}
        for c in cities
    ]
    rows.sort(key=lambda r: -Decimal(r["contribution"]))
    platform = line(None) if None in ledger else None
    totals = {}
    for key in ("trips", "gmv", "revenue", "costs", "contribution", "promotions", "gst_collected"):
        values = [Decimal(str(r[key])) for r in rows] + (
            [Decimal(str(platform[key]))] if platform else []
        )
        totals[key] = str(sum(values, ZERO)) if key != "trips" else int(sum(values))
    return {
        "month": start.date().isoformat(),
        "cities": rows,
        "not_city": platform,
        "totals": totals,
        "assumptions": {k: str(v) for k, v in rules.items()},
    }


def set_budget(city, month: date, *, revenue, promotions, user):
    from .models import CityBudget

    budget, _ = CityBudget.objects.update_or_create(
        city=city,
        month=month.replace(day=1),
        defaults={"revenue": revenue, "promotions": promotions, "updated_by": user},
    )
    return budget
