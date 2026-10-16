from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.dates import day_bounds, week_start
from apps.core.validators import normalize_registration, registration_validator
from apps.payments.services import driver_earnings, wallet_balance
from apps.pricing.models import RideType

from . import goals, services
from .models import DocumentStatus, DriverDocument, DriverProfile, Vehicle


class IsDriver(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_driver and hasattr(user, "driver_profile")
        )


class VehicleSerializer(serializers.ModelSerializer):
    ride_type = serializers.SlugRelatedField(slug_field="code", queryset=RideType.objects.all())
    registration_display = serializers.CharField(read_only=True)
    # Declared explicitly so "TN 09 AB 1234" is normalised before it is validated.
    registration_number = serializers.CharField(max_length=15)

    def validate_registration_number(self, value: str) -> str:
        value = normalize_registration(value)
        try:
            registration_validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        if Vehicle.objects.filter(registration_number=value).exists():
            raise serializers.ValidationError("This vehicle is already registered.")
        return value

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "ride_type",
            "make",
            "model",
            "registration_number",
            "registration_display",
            "year",
            "color",
            "seats",
            "is_active",
        ]
        read_only_fields = ["is_active"]


class DocumentSerializer(serializers.ModelSerializer):
    driver = serializers.IntegerField(source="driver_id", read_only=True)
    driver_name = serializers.CharField(source="driver.name", read_only=True)

    class Meta:
        model = DriverDocument
        fields = [
            "id",
            "driver",
            "driver_name",
            "doc_type",
            "number_last4",
            "file",
            "expires_on",
            "status",
            "rejection_reason",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["status", "rejection_reason", "reviewed_at", "created_at"]


class DriverSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    city = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    vehicle = serializers.SerializerMethodField()
    wallet_balance = serializers.SerializerMethodField()

    class Meta:
        model = DriverProfile
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "city",
            "license_number",
            "license_expiry",
            "onboarding_status",
            "availability",
            "current_lat",
            "current_lng",
            "location_updated_at",
            "rating",
            "rating_count",
            "acceptance_rate",
            "completed_trips",
            "cancelled_trips",
            "safety_score",
            "approved_at",
            "suspended_reason",
            "vehicle",
            "wallet_balance",
        ]

    def get_vehicle(self, driver) -> dict | None:
        vehicle = driver.active_vehicle
        return VehicleSerializer(vehicle).data if vehicle else None

    def get_wallet_balance(self, driver) -> str:
        annotated = getattr(driver, "wallet_amount", None)  # lists annotate it in one query
        return str(annotated if annotated is not None else wallet_balance(driver.user))


class DriverStatusSerializer(DriverSerializer):
    missing_documents = serializers.SerializerMethodField()
    compliance_problems = serializers.SerializerMethodField()
    going_home_uses_left = serializers.SerializerMethodField()

    class Meta(DriverSerializer.Meta):
        fields = [
            *DriverSerializer.Meta.fields,
            "missing_documents",
            "compliance_problems",
            "home_lat",
            "home_lng",
            "home_address",
            "going_home_until",
            "going_home_uses_left",
            "accepts_parcels",
            "accepts_intercity",
        ]

    def get_going_home_uses_left(self, driver) -> int:
        return goals.uses_left(driver)

    def get_missing_documents(self, driver) -> list[str]:
        return services.missing_documents(driver)

    def get_compliance_problems(self, driver) -> list[str]:
        return services.compliance_problems(driver)


class HomeSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    address = serializers.CharField(required=False, allow_blank=True, max_length=255)


class GoingHomeSerializer(serializers.Serializer):
    on = serializers.BooleanField()


class ParcelsSerializer(serializers.Serializer):
    on = serializers.BooleanField()


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    speed_kmh = serializers.FloatField(required=False, allow_null=True, min_value=0)
    heading = serializers.FloatField(required=False, allow_null=True, min_value=0, max_value=360)
    # Set when the app replays fixes it saved while offline: when the phone took the fix.
    recorded_at = serializers.DateTimeField(required=False)

    def validate_recorded_at(self, value):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        if value > now + timedelta(seconds=30) or value < now - timedelta(minutes=30):
            raise serializers.ValidationError("Location fixes can be replayed for 30 minutes.")
        return value


class LocationBatchSerializer(serializers.Serializer):
    fixes = LocationSerializer(many=True, max_length=200)


class EarningsSerializer(serializers.Serializer):
    period = serializers.CharField()
    trips = serializers.IntegerField()
    fares = serializers.DecimalField(max_digits=12, decimal_places=2)
    earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    trip_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    tips = serializers.DecimalField(max_digits=12, decimal_places=2)
    cancellation_fees = serializers.DecimalField(max_digits=12, decimal_places=2)
    commission = serializers.DecimalField(max_digits=12, decimal_places=2)
    cash_collected = serializers.DecimalField(max_digits=12, decimal_places=2)
    distance_km = serializers.DecimalField(max_digits=12, decimal_places=2)
    daily = serializers.ListField(child=serializers.DictField())


class DayPassSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["WALLET", "UPI"])
    payer_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)


class CounterSerializer(serializers.Serializer):
    extra = serializers.DecimalField(max_digits=5, decimal_places=2)


class DriverAppViewSet(ContextBindingMixin, GenericViewSet):
    """Endpoints the driver app uses: availability, GPS, offers, earnings, documents."""

    permission_classes = [IsDriver]
    serializer_class = DriverStatusSerializer
    throttle_scope: str | None = None  # set per action (GPS updates get their own budget)
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DriverProfile.objects.none()
        return DriverProfile.objects.filter(user=self.request.user)

    @property
    def driver(self) -> DriverProfile:
        return (
            DriverProfile.objects.select_related("user", "city")
            .prefetch_related("vehicles")
            .get(user=self.request.user)
        )

    @extend_schema(responses=DriverStatusSerializer)
    @action(detail=False, methods=["get"])
    def me(self, request):
        return Response(DriverStatusSerializer(self.driver).data)

    @extend_schema(request=ParcelsSerializer, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"])
    def parcels(self, request):
        """Bike drivers: take parcel deliveries too (on by default)."""
        serializer = ParcelsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = self.driver
        driver.accepts_parcels = serializer.validated_data["on"]
        driver.save(update_fields=["accepts_parcels", "updated_at"])
        return Response(DriverStatusSerializer(driver).data)

    @extend_schema(request=ParcelsSerializer, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"])
    def intercity(self, request):
        """Car drivers: take intercity trips too (hours away from your city)."""
        serializer = ParcelsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = self.driver
        driver.accepts_intercity = serializer.validated_data["on"]
        driver.save(update_fields=["accepts_intercity", "updated_at"])
        return Response(DriverStatusSerializer(driver).data)

    @extend_schema(request=LocationSerializer, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"])
    def online(self, request):
        serializer = LocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.go_online(
            self.driver, lat=serializer.validated_data["lat"], lng=serializer.validated_data["lng"]
        )
        return Response(DriverStatusSerializer(self.driver).data)

    @extend_schema(request=None, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"])
    def offline(self, request):
        services.go_offline(self.driver)
        return Response(DriverStatusSerializer(self.driver).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="lost-items")
    def lost_items(self, request):
        """Riders' lost-item reports waiting for this driver's answer."""
        from apps.rides.api import LostItemSerializer
        from apps.rides.models import LostItemReport, LostItemStatus

        items = LostItemReport.objects.filter(
            trip__driver=self.driver, status__in=[LostItemStatus.REPORTED, LostItemStatus.FOUND]
        ).select_related("trip__rider__user")
        return Response(LostItemSerializer(items, many=True).data)

    @extend_schema(request=DayPassSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"], url_path="day-pass")
    def day_pass(self, request):
        """Zero-commission day pass: today's price and status (GET), or buy it (POST)."""
        from . import day_pass

        driver = self.driver
        if request.method == "POST":
            serializer = DayPassSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            day_pass.buy(driver, **serializer.validated_data)
        return Response(day_pass.status(driver))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def wellbeing(self, request):
        """Driving time in the current stretch, time to the next break, and any break running."""
        from . import wellbeing

        return Response(wellbeing.status(self.driver))

    @extend_schema(
        parameters=[OpenApiParameter("days", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="fair-share")
    def fair_share(self, request):
        """Real earnings: gross, commission, running costs and the hourly figure after costs."""
        from apps.rides.fair_share import driver_summary

        try:
            days = min(max(int(request.query_params.get("days", 7)), 1), 30)
        except ValueError:
            days = 7
        return Response(driver_summary(self.driver, days=days))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def goals(self, request):
        """Today's goals: trips completed and the bonus tiers reached."""
        return Response(goals.progress(self.driver))

    @extend_schema(request=HomeSerializer, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"])
    def home(self, request):
        serializer = HomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            DriverStatusSerializer(goals.set_home(self.driver, **serializer.validated_data)).data
        )

    @extend_schema(request=GoingHomeSerializer, responses=DriverStatusSerializer)
    @action(detail=False, methods=["post"], url_path="going-home")
    def going_home(self, request):
        """Only offer trips that bring me closer to home (for an hour, twice a day)."""
        serializer = GoingHomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = goals.set_going_home(self.driver, on=serializer.validated_data["on"])
        return Response(DriverStatusSerializer(driver).data)

    @extend_schema(request=LocationSerializer, responses={204: None})
    @action(detail=False, methods=["post"], throttle_scope="location")
    def location(self, request):
        serializer = LocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        services.update_location(self.driver, now=data.pop("recorded_at", None), **data)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=LocationBatchSerializer, responses={204: None})
    @action(detail=False, methods=["post"], url_path="location/batch", throttle_scope="location")
    def location_batch(self, request):
        """Fixes saved while the phone was offline, replayed in order once it reconnects. They
        go into the GPS trail (distance, Ride Check); only the newest moves the car on the map."""
        serializer = LocationBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fixes = sorted(
            serializer.validated_data["fixes"],
            key=lambda f: f.get("recorded_at") or timezone.now(),
        )
        driver = self.driver
        for fix in fixes:
            fix = dict(fix)
            services.update_location(driver, now=fix.pop("recorded_at", None), **fix)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 204: None})
    @action(detail=False, methods=["get"])
    def offer(self, request):
        """The pending trip offer, if any (polling fallback for the WebSocket)."""
        from apps.rides.dispatch import offer_payload
        from apps.rides.models import OfferStatus, TripOffer

        offer = (
            TripOffer.objects.filter(
                driver__user=request.user, status=OfferStatus.PENDING, expires_at__gt=timezone.now()
            )
            .select_related("trip__ride_type")
            .first()
        )
        if offer is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(offer_payload(offer))

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"offers/(?P<offer_id>\d+)/accept")
    def accept(self, request, offer_id=None):
        from apps.rides.api import TripSerializer
        from apps.rides.dispatch import accept_offer
        from apps.rides.models import TripOffer

        offer = get_object_or_404(TripOffer, pk=offer_id, driver__user=request.user)
        trip = accept_offer(offer, driver=self.driver)
        return Response(TripSerializer(trip, context={"request": request}).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=False, methods=["post"], url_path=r"offers/(?P<offer_id>\d+)/decline")
    def decline(self, request, offer_id=None):
        from apps.rides.dispatch import decline_offer
        from apps.rides.models import TripOffer

        offer = get_object_or_404(TripOffer, pk=offer_id, driver__user=request.user)
        decline_offer(offer, driver=self.driver)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=CounterSerializer, responses={204: None})
    @action(detail=False, methods=["post"], url_path=r"offers/(?P<offer_id>\d+)/counter")
    def counter(self, request, offer_id=None):
        """Bid your fare: "I'll do it for ₹X more" instead of accepting the rider's offer."""
        from apps.rides import bids
        from apps.rides.models import TripOffer

        serializer = CounterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offer = get_object_or_404(TripOffer, pk=offer_id, driver__user=request.user)
        bids.counter(offer, driver=self.driver, extra=serializer.validated_data["extra"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[OpenApiParameter("period", str, enum=["today", "week", "month"])],
        responses=EarningsSerializer,
    )
    @action(detail=False, methods=["get"])
    def earnings(self, request):
        period = request.query_params.get("period", "week")
        today = timezone.localdate()
        first_day = {"today": today, "month": today.replace(day=1)}.get(period, week_start(today))
        start, _ = day_bounds(first_day)
        _, end = day_bounds(today)
        driver = self.driver
        summary = driver_earnings(driver, start=start, end=end)
        daily = []
        day = first_day
        while day <= today:
            day_start, day_end = day_bounds(day)
            row = driver_earnings(driver, start=day_start, end=day_end)
            daily.append(
                {"date": day.isoformat(), "earnings": str(row["earnings"]), "trips": row["trips"]}
            )
            day += timedelta(days=1)
        return Response(EarningsSerializer({"period": period, **summary, "daily": daily}).data)

    @extend_schema(request=DocumentSerializer, responses=DocumentSerializer(many=True))
    @action(detail=False, methods=["get", "post"])
    def documents(self, request):
        driver = self.driver
        if request.method == "POST":
            serializer = DocumentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            services.submit_document(driver, **serializer.validated_data)
        current = driver.documents.exclude(status=DocumentStatus.SUPERSEDED)
        return Response(DocumentSerializer(current, many=True, context={"request": request}).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def surge(self, request):
        """Zones in the driver's city where prices are surging: worth driving towards."""
        from apps.pricing.services import surge_board

        board = surge_board(self.driver.city)
        return Response(
            [
                {
                    "zone": row["zone"].name,
                    "lat": row["zone"].center_lat,
                    "lng": row["zone"].center_lng,
                    "radius_km": row["zone"].radius_km,
                    "multiplier": str(row["multiplier"]),
                }
                for row in board
                if row["multiplier"] > 1
            ]
        )

    @extend_schema(request=VehicleSerializer, responses=VehicleSerializer)
    @action(detail=False, methods=["post"])
    def vehicle(self, request):
        serializer = VehicleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vehicle = services.register_vehicle(self.driver, **serializer.validated_data)
        return Response(VehicleSerializer(vehicle).data, status=status.HTTP_201_CREATED)


class ReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class DriverViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Drivers, for operations staff: onboarding, verification and suspension."""

    queryset = DriverProfile.objects.select_related("user", "city").prefetch_related(
        "vehicles__ride_type"
    )
    serializer_class = DriverStatusSerializer

    def get_serializer_class(self):
        # The list is a table: no per-driver document and compliance checks (the detail
        # view still has them).
        return DriverSerializer if self.action == "list" else DriverStatusSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            from decimal import Decimal

            from django.db.models import DecimalField, OuterRef, Subquery, Value
            from django.db.models.functions import Coalesce

            from apps.payments.models import Wallet

            queryset = queryset.annotate(
                wallet_amount=Coalesce(
                    Subquery(
                        Wallet.objects.filter(user_id=OuterRef("user_id")).values("balance")[:1]
                    ),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        return queryset

    filterset_fields = ["city__slug", "onboarding_status", "availability"]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "license_number",
        "vehicles__registration_number",
    ]
    ordering_fields = ["created_at", "rating", "completed_trips", "acceptance_rate", "safety_score"]
    capabilities = {
        "list": Cap.DRIVERS_VIEW,
        "retrieve": Cap.DRIVERS_VIEW,
        "documents": Cap.DRIVERS_VIEW,
        "suspend": Cap.DRIVERS_MANAGE,
        "reinstate": Cap.DRIVERS_MANAGE,
        "review_document": Cap.DRIVERS_VERIFY,
        "verification_queue": Cap.DRIVERS_VERIFY,
    }

    @extend_schema(responses=DocumentSerializer(many=True))
    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        driver = self.get_object()
        current = driver.documents.exclude(status=DocumentStatus.SUPERSEDED)
        return Response(DocumentSerializer(current, many=True, context={"request": request}).data)

    @extend_schema(responses=DocumentSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="verification-queue")
    def verification_queue(self, request):
        pending = DriverDocument.objects.filter(status=DocumentStatus.PENDING).select_related(
            "driver__user"
        )
        return Response(DocumentSerializer(pending, many=True, context={"request": request}).data)

    @extend_schema(request=ReviewSerializer, responses=DocumentSerializer)
    @action(detail=False, methods=["post"], url_path=r"documents/(?P<document_id>\d+)/review")
    def review_document(self, request, document_id=None):
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = get_object_or_404(DriverDocument, pk=document_id)
        services.review_document(
            document,
            approve=serializer.validated_data["approve"],
            reviewer=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(DocumentSerializer(document, context={"request": request}).data)

    @extend_schema(request=ReasonSerializer, responses=DriverStatusSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = services.suspend_driver(
            self.get_object(), reason=serializer.validated_data["reason"], actor=request.user
        )
        return Response(DriverStatusSerializer(driver).data)

    @extend_schema(request=None, responses=DriverStatusSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        driver = services.reinstate_driver(self.get_object(), actor=request.user)
        return Response(DriverStatusSerializer(driver).data)
