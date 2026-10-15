from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.exceptions import ActionNotPermitted
from apps.geo.models import City

from . import services
from .models import FareRule, PriceAlert, PriceAlertStatus, PromoCode, RideType, SurgeOverride


class RideTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RideType
        fields = ["id", "code", "name", "description", "seats"]


class RideTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RideType.objects.filter(is_active=True)
    serializer_class = RideTypeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    lookup_field = "code"


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    address = serializers.CharField(required=False, allow_blank=True, max_length=255)


def split_stops(data: dict) -> dict:
    """``stops`` (up to 3, in order) or the older single ``stop``, as service arguments."""
    stops = data.get("stops") or ([data["stop"]] if data.get("stop") else [])
    if data.get("stops") and data.get("stop"):
        raise serializers.ValidationError({"stops": ["Send either stop or stops, not both."]})
    if not stops:
        return {}
    first = stops[0]
    return {
        "stop": (first["lat"], first["lng"]),
        "stop_address": first.get("address", ""),
        "extra_stops": [dict(s) for s in stops[1:]],
    }


class FareLineSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    kind = serializers.CharField()


class FareSerializer(serializers.Serializer):
    lines = FareLineSerializer(many=True)
    surge_multiplier = serializers.DecimalField(max_digits=3, decimal_places=1)
    ride_fare = serializers.DecimalField(max_digits=10, decimal_places=2)
    surge_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    fees = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(max_digits=10, decimal_places=2)
    gst = serializers.DecimalField(max_digits=10, decimal_places=2)
    total = serializers.DecimalField(max_digits=10, decimal_places=2)


class EstimateRequestSerializer(serializers.Serializer):
    pickup = PointSerializer()
    dropoff = PointSerializer()
    stop = PointSerializer(required=False, allow_null=True)
    stops = PointSerializer(many=True, required=False, max_length=3)
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=20)
    service = serializers.ChoiceField(choices=["RIDE", "PARCEL"], required=False, default="RIDE")


class AlternativeSerializer(serializers.Serializer):
    ride_type = serializers.CharField()
    name = serializers.CharField()
    pickup_eta_min = serializers.IntegerField(allow_null=True)
    fare_total = serializers.DecimalField(max_digits=9, decimal_places=2)


class SureRideQuoteSerializer(serializers.Serializer):
    minutes = serializers.IntegerField()
    fee = serializers.DecimalField(max_digits=6, decimal_places=2)
    refund = serializers.DecimalField(max_digits=6, decimal_places=2)


class OfferRangeSerializer(serializers.Serializer):
    min = serializers.DecimalField(max_digits=9, decimal_places=2)
    max = serializers.DecimalField(max_digits=9, decimal_places=2)


class EstimateOptionSerializer(serializers.Serializer):
    ride_type = RideTypeSerializer()
    distance_km = serializers.DecimalField(max_digits=7, decimal_places=2)
    duration_minutes = serializers.DecimalField(max_digits=7, decimal_places=2)
    route_polyline = serializers.CharField(allow_blank=True)
    pickup_eta_min = serializers.IntegerField(allow_null=True)
    availability = serializers.ChoiceField(choices=["AVAILABLE", "NONE", "CLOSED"])
    unavailable_reason = serializers.CharField(allow_blank=True)
    suggestion = AlternativeSerializer(allow_null=True)
    sure_ride = SureRideQuoteSerializer(allow_null=True)
    fare_lock = serializers.BooleanField()
    offer_range = OfferRangeSerializer()
    fare = FareSerializer()


class EstimateResponseSerializer(serializers.Serializer):
    city = serializers.CharField()
    promo_error = serializers.CharField()
    options = EstimateOptionSerializer(many=True)


def serialize_options(result: dict) -> dict:
    return {
        "city": result["city"].slug,
        "promo_error": result["promo_error"],
        "options": [
            {
                "ride_type": option["ride_type"],
                "distance_km": option["estimate"].route.distance_km,
                "duration_minutes": option["estimate"].route.duration_minutes,
                "route_polyline": option["estimate"].route.polyline,
                "pickup_eta_min": option["pickup_eta_min"],
                "availability": option["availability"],
                "unavailable_reason": option["unavailable_reason"],
                "suggestion": option["suggestion"],
                "sure_ride": option["sure_ride"],
                "fare_lock": option["fare_lock"],
                "offer_range": option["offer_range"],
                "fare": option["estimate"].fare,
            }
            for option in result["options"]
        ],
    }


class FareEstimateView(ContextBindingMixin, APIView):
    """Upfront fares and pickup ETAs for every ride type between two points."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "fare_estimate"

    @extend_schema(
        request=EstimateRequestSerializer, responses=EstimateResponseSerializer, tags=["fares"]
    )
    def post(self, request):
        from apps.rides.services import estimate_options

        user = request.user
        if user.is_driver or (user.is_staff_member and not user.has_capability(Cap.PRICING_VIEW)):
            raise ActionNotPermitted("Only riders and pricing staff can request estimates.")
        serializer = EstimateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = estimate_options(
            rider=getattr(user, "rider_profile", None),
            pickup=(data["pickup"]["lat"], data["pickup"]["lng"]),
            dropoff=(data["dropoff"]["lat"], data["dropoff"]["lng"]),
            promo_code=data.get("promo_code", ""),
            service=data.get("service", "RIDE"),
            **{k: v for k, v in split_stops(data).items() if k != "stop_address"},
        )
        return Response(EstimateResponseSerializer(serialize_options(result)).data)


class FareRuleSerializer(serializers.ModelSerializer):
    city = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    ride_type = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = FareRule
        fields = [
            "id",
            "city",
            "ride_type",
            "base_fare",
            "per_km",
            "per_minute",
            "minimum_fare",
            "booking_fee",
            "cancellation_fee",
            "free_wait_minutes",
            "wait_per_minute",
            "airport_fee",
            "is_active",
        ]


class FareRuleViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, BaseViewSet
):
    """Fare cards per city and ride type."""

    queryset = FareRule.objects.select_related("city", "ride_type")
    serializer_class = FareRuleSerializer
    filterset_fields = ["city__slug", "ride_type__code", "is_active"]
    capabilities = {
        "list": Cap.PRICING_VIEW,
        "retrieve": Cap.PRICING_VIEW,
        "update": Cap.PRICING_MANAGE,
        "partial_update": Cap.PRICING_MANAGE,
    }
    http_method_names = ["get", "patch"]


class SurgeZoneSerializer(serializers.Serializer):
    zone_id = serializers.IntegerField(source="zone.pk")
    zone = serializers.CharField(source="zone.name")
    lat = serializers.FloatField(source="zone.center_lat")
    lng = serializers.FloatField(source="zone.center_lng")
    multiplier = serializers.DecimalField(max_digits=3, decimal_places=1)
    demand = serializers.IntegerField()
    supply = serializers.IntegerField()
    computed_at = serializers.DateTimeField(allow_null=True)


class SurgeOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurgeOverride
        fields = [
            "id",
            "zone",
            "multiplier",
            "starts_at",
            "ends_at",
            "reason",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "Must be after the start."})
        return attrs


class SurgeViewSet(BaseViewSet):
    """Live surge multipliers by zone, and manual overrides."""

    queryset = SurgeOverride.objects.select_related("zone")
    serializer_class = SurgeOverrideSerializer
    capabilities = {
        "board": Cap.PRICING_VIEW,
        "recompute": Cap.PRICING_MANAGE,
        "overrides": Cap.PRICING_VIEW,
        "create_override": Cap.PRICING_MANAGE,
    }

    @extend_schema(
        parameters=[OpenApiParameter("city", str, required=True, description="City slug")],
        responses=SurgeZoneSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def board(self, request):
        city = get_object_or_404(City, slug=request.query_params.get("city", ""))
        return Response(SurgeZoneSerializer(services.surge_board(city), many=True).data)

    @extend_schema(request=None, responses={200: None})
    @action(detail=False, methods=["post"])
    def recompute(self, request):
        return Response({"snapshots": len(services.recompute_surge())})

    @extend_schema(responses=SurgeOverrideSerializer(many=True))
    @action(detail=False, methods=["get"])
    def overrides(self, request):
        active = self.get_queryset().filter(ends_at__gt=timezone.now())
        return Response(SurgeOverrideSerializer(active, many=True).data)

    @extend_schema(request=SurgeOverrideSerializer, responses={201: SurgeOverrideSerializer})
    @overrides.mapping.post
    def create_override(self, request):
        serializer = SurgeOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=201)


class PromoCodeSerializer(serializers.ModelSerializer):
    usage = serializers.SerializerMethodField()

    class Meta:
        model = PromoCode
        fields = [
            "id",
            "code",
            "description",
            "discount_type",
            "value",
            "max_discount",
            "min_fare",
            "valid_from",
            "valid_until",
            "max_redemptions",
            "max_per_rider",
            "first_ride_only",
            "city",
            "ride_types",
            "is_active",
            "usage",
        ]

    def get_usage(self, promo) -> dict:
        return services.promo_usage(promo)


class PromoCodeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    BaseViewSet,
):
    queryset = PromoCode.objects.all()
    serializer_class = PromoCodeSerializer
    capabilities = {"*": Cap.PROMOS_MANAGE}
    filterset_fields = ["is_active", "discount_type", "city"]
    search_fields = ["code", "description"]
    http_method_names = ["get", "post", "patch"]


class PriceAlertSerializer(serializers.ModelSerializer):
    ride_type = serializers.SlugRelatedField(slug_field="code", read_only=True)
    ride_type_name = serializers.CharField(source="ride_type.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PriceAlert
        fields = [
            "id",
            "ride_type",
            "ride_type_name",
            "pickup_address",
            "dropoff_address",
            "dropoff_lat",
            "dropoff_lng",
            "fare_when_set",
            "surge_when_set",
            "status",
            "status_label",
            "expires_at",
            "notified_at",
            "fare_when_notified",
        ]


class PriceAlertRequestSerializer(serializers.Serializer):
    ride_type = serializers.SlugRelatedField(
        slug_field="code", queryset=RideType.objects.filter(is_active=True)
    )
    pickup = PointSerializer()
    dropoff = PointSerializer()


class PriceAlertViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, BaseViewSet):
    """Routes a rider asked to watch ("tell me when prices drop") while surge pricing is on."""

    queryset = PriceAlert.objects.select_related("ride_type")
    serializer_class = PriceAlertSerializer
    rider_lookup = "rider"
    rider_actions = ("list", "create", "cancel")
    filterset_fields = ["status"]

    @extend_schema(request=PriceAlertRequestSerializer, responses={201: PriceAlertSerializer})
    def create(self, request, *args, **kwargs):
        from . import alerts

        serializer = PriceAlertRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        alert = alerts.create_alert(
            request.user.rider_profile,
            ride_type=data["ride_type"],
            pickup=(data["pickup"]["lat"], data["pickup"]["lng"]),
            dropoff=(data["dropoff"]["lat"], data["dropoff"]["lng"]),
            pickup_address=data["pickup"].get("address", ""),
            dropoff_address=data["dropoff"].get("address", ""),
        )
        return Response(PriceAlertSerializer(alert).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=PriceAlertSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        alert = self.get_object()
        if alert.status == PriceAlertStatus.ACTIVE:
            alert.status = PriceAlertStatus.CANCELLED
            alert.save(update_fields=["status"])
        return Response(PriceAlertSerializer(alert).data)
