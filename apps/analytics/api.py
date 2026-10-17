import csv
from datetime import timedelta

from django.core.cache import cache
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import CapabilityPermission, ContextBindingMixin
from apps.geo.models import City
from apps.rides.models import Trip

from . import services

PARAMS = [
    OpenApiParameter("city", str, description="City slug (default: all cities)"),
    OpenApiParameter("days", int, description="Look-back window in days (default 7, max 90)"),
]


class AnalyticsView(ContextBindingMixin, APIView):
    permission_classes = [CapabilityPermission]
    capabilities = {"get": Cap.REPORTS_VIEW}
    cache_seconds = 30

    def window(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 7)), 1), 90)
        except ValueError:
            days = 7
        until = timezone.now()
        city = City.objects.filter(slug=request.query_params.get("city", "")).first()
        return {"since": until - timedelta(days=days), "until": until, "city": city}, days

    def compute(self, request, window: dict, days: int):  # pragma: no cover - abstract
        raise NotImplementedError

    @extend_schema(parameters=PARAMS, responses={200: OpenApiTypes.OBJECT}, tags=["analytics"])
    def get(self, request):
        window, days = self.window(request)
        key = f"analytics:{type(self).__name__}:{request.query_params.urlencode()}"
        data = cache.get(key)
        if data is None:
            data = self.compute(request, window, days)
            cache.set(key, data, self.cache_seconds)
        return Response(data)


class OverviewView(AnalyticsView):
    """Headline KPIs for the window plus the live state of the marketplace."""

    cache_seconds = 10

    def compute(self, request, window, days):
        return {
            "days": days,
            "kpis": services.overview(**window),
            "live": services.live_status(city=window["city"]),
            "driver_hours_online": services.hours_online(**window),
        }


class TimeSeriesView(AnalyticsView):
    """Trips and GMV per hour (windows up to 2 days) or per day."""

    def compute(self, request, window, days):
        unit = "hour" if days <= 2 else "day"
        return {"unit": unit, "series": services.time_series(unit=unit, **window)}


class BreakdownView(AnalyticsView):
    """Zones, ride types, demand by hour of day, heatmap cells and top drivers."""

    def compute(self, request, window, days):
        return {
            "zones": services.zone_performance(**window),
            "ride_types": services.ride_type_mix(**window),
            "hourly": services.hourly_demand(**window),
            "heatmap": services.demand_heatmap(**window),
            "leaderboard": services.driver_leaderboard(**window),
        }


class _Echo:
    def write(self, value):
        return value


class TripExportView(AnalyticsView):
    """Stream completed and cancelled trips as CSV (constant memory, any size)."""

    COLUMNS = [
        "trip_number",
        "status",
        "city__name",
        "ride_type__code",
        "requested_at",
        "completed_at",
        "pickup_address",
        "dropoff_address",
        "actual_distance_km",
        "fare_total",
        "driver_earning",
        "platform_commission",
        "gst_amount",
        "discount_amount",
        "tip_amount",
        "payment_method",
        "surge_multiplier",
    ]

    @extend_schema(parameters=PARAMS, responses={(200, "text/csv"): bytes}, tags=["analytics"])
    def get(self, request):
        window, _ = self.window(request)
        rows = (
            Trip.objects.filter(requested_at__gte=window["since"], requested_at__lt=window["until"])
            .filter(**({"city": window["city"]} if window["city"] else {}))
            .order_by("requested_at")
            .values_list(*self.COLUMNS)
        )
        writer = csv.writer(_Echo())

        def stream():
            yield writer.writerow(self.COLUMNS)
            for row in rows.iterator(chunk_size=2000):
                yield writer.writerow(row)

        response = StreamingHttpResponse(stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="ride-pulse-trips.csv"'
        return response


class WarehouseInsightsView(ContextBindingMixin, APIView):
    """The data platform's latest summary (data/reports/insights.json, written by the nightly
    pipeline). The app never opens the warehouse itself: the pipeline publishes this file."""

    permission_classes = [CapabilityPermission]
    capabilities = {"get": Cap.REPORTS_VIEW}

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["analytics"])
    def get(self, request):
        import json

        from django.conf import settings

        path = settings.DATA_INSIGHTS_PATH
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return Response(
                {
                    "available": False,
                    "message": "No data-platform run yet. Run `make data-run` (data/README.md).",
                }
            )
        except ValueError:
            return Response({"available": False, "message": "The insights file is unreadable."})
        return Response({"available": True, **data})


# --- City P&L -------------------------------------------------------------------------------


class BudgetSerializer(serializers.Serializer):
    city = serializers.SlugRelatedField(slug_field="slug", queryset=City.objects.all())
    month = serializers.DateField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    promotions = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class PnlView(APIView):
    """Profit and loss by city for a month (``?month=2026-10``), and setting budgets."""

    permission_classes = [CapabilityPermission]
    capabilities = {"get": Cap.PAYMENTS_VIEW, "post": Cap.PAYOUTS_MANAGE}

    @extend_schema(
        parameters=[OpenApiParameter("month", str, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        from datetime import date

        from django.utils import timezone

        from . import pnl

        raw = request.query_params.get("month")
        month = date.fromisoformat(f"{raw}-01") if raw else timezone.localdate().replace(day=1)
        return Response(pnl.report(month))

    @extend_schema(request=BudgetSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from . import pnl

        data = BudgetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        budget = pnl.set_budget(
            v["city"],
            v["month"],
            revenue=v["revenue"],
            promotions=v["promotions"],
            user=request.user,
        )
        return Response({"city": budget.city.slug, "month": budget.month})
