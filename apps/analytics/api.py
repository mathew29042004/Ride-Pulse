import csv
from datetime import timedelta

from django.core.cache import cache
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
