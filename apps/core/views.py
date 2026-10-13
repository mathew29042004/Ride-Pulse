from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness and readiness probe used by Docker and load balancers."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    @extend_schema(
        tags=["system"],
        responses=inline_serializer(
            "Health",
            {
                "status": serializers.CharField(),
                "database": serializers.CharField(),
                "time": serializers.DateTimeField(),
            },
        ),
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database = "ok"
        except Exception:  # pragma: no cover - exercised only when the DB is down
            database = "unavailable"
        healthy = database == "ok"
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "database": database,
                "time": timezone.now(),
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class ConfigView(APIView):
    """Public client configuration: which map provider to use, branding and currency."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["system"],
        responses=inline_serializer(
            "ClientConfig",
            {
                "company_name": serializers.CharField(),
                "currency_symbol": serializers.CharField(),
                "maps": serializers.DictField(),
                "payments": serializers.DictField(),
            },
        ),
    )
    def get(self, request):
        from django.conf import settings

        from apps.core.conf import company_name, currency_symbol
        from apps.payments import razorpay

        browser_key = settings.GOOGLE_MAPS_BROWSER_KEY
        return Response(
            {
                "company_name": company_name(),
                "currency_symbol": currency_symbol(),
                "maps": {
                    "provider": "google" if browser_key else "osm",
                    "browser_key": browser_key,
                    "map_id": settings.GOOGLE_MAPS_MAP_ID,
                    "routes": "google" if settings.GOOGLE_MAPS_API_KEY else "estimate",
                },
                # The publishable key only; the secret never leaves the server.
                "payments": {"razorpay_key_id": razorpay.key_id()},
                "push": {"vapid_public_key": settings.VAPID_PUBLIC_KEY},
            }
        )
