from datetime import timedelta
from decimal import Decimal

import django_filters
from django.db.models import Prefetch
from django.http import HttpResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, CapabilityPermission, ContextBindingMixin
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation, ConflictError
from apps.drivers.models import Availability, DriverProfile, Vehicle
from apps.payments.models import PaymentMethod
from apps.pricing.api import FareSerializer, PointSerializer
from apps.pricing.models import RideType
from apps.support.api import IncidentSerializer

from . import calls, dispatch, invoices, lost_items, pickup, safety, services, splits
from .models import (
    ACTIVE_STATUSES,
    FareSplit,
    LostItemReport,
    RideCheck,
    RideCheckKind,
    RideCheckStatus,
    RidePreference,
    ScheduledRide,
    Trip,
    TripEvent,
    TripMessage,
    TripOffer,
    TripPaymentStatus,
    TripStatus,
)
from .receipts import render_receipt


class TripPartySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    rating = serializers.DecimalField(max_digits=3, decimal_places=2)
    phone = serializers.SerializerMethodField()

    def get_phone(self, party) -> str | None:
        """Riders and drivers never see each other's number (they call through the masked
        bridge); staff do, for support and safety."""
        request = self.context.get("request")
        viewer = request.user if request else None
        return party.user.phone if viewer is not None and viewer.is_staff_member else None


class RideCheckSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    rider_name = serializers.CharField(source="trip.rider.name", read_only=True)
    driver_name = serializers.CharField(source="trip.driver.user.get_full_name", read_only=True)
    incident_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = RideCheck
        fields = [
            "id",
            "trip_id",
            "trip_number",
            "rider_name",
            "driver_name",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "lat",
            "lng",
            "driver_ok",
            "incident_id",
            "created_at",
            "answered_at",
        ]


class RideCheckAnswerSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class TripSerializer(serializers.ModelSerializer):
    ride_type = serializers.SlugRelatedField(slug_field="code", read_only=True)
    ride_type_name = serializers.CharField(source="ride_type.name", read_only=True)
    city = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    rider = TripPartySerializer(read_only=True)
    driver = TripPartySerializer(read_only=True, allow_null=True)
    driver_location = serializers.SerializerMethodField()
    vehicle = serializers.StringRelatedField()
    otp = serializers.SerializerMethodField()
    fare = serializers.SerializerMethodField()
    promo_code = serializers.CharField(source="promo.code", default=None, read_only=True)
    has_rated = serializers.SerializerMethodField()
    stop = serializers.SerializerMethodField()
    is_favourite_driver = serializers.SerializerMethodField()
    open_ride_check = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id",
            "trip_number",
            "status",
            "status_label",
            "ride_type",
            "ride_type_name",
            "city",
            "pickup_lat",
            "pickup_lng",
            "pickup_address",
            "dropoff_lat",
            "dropoff_lng",
            "dropoff_address",
            "rider",
            "driver",
            "driver_location",
            "vehicle",
            "otp",
            "payment_method",
            "promo_code",
            "estimated_distance_km",
            "estimated_duration_min",
            "surge_multiplier",
            "estimated_fare",
            "route_polyline",
            "route_source",
            "pickup_eta_min",
            "requested_at",
            "assigned_at",
            "arrived_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "cancellation_fee",
            "actual_distance_km",
            "actual_duration_min",
            "waiting_minutes",
            "pricing_mode",
            "fare",
            "fare_total",
            "driver_earning",
            "tip_amount",
            "payment_status",
            "flags",
            "has_rated",
            "stop",
            "car_confirmed_at",
            "invoice_number",
            "invoice_emailed_at",
            "boost_amount",
            "tip_pledged",
            "preferences",
            "is_favourite_driver",
            "night_safe",
            "early_drop_confirmed",
            "contacts_notified_at",
            "home_safe_at",
            "open_ride_check",
        ]

    def _viewer(self):
        request = self.context.get("request")
        return request.user if request else None

    def get_otp(self, trip) -> str | None:
        """Only the rider sees the ride PIN, and only once the driver is close (so it can't be
        passed on early); they show the QR or read the PIN out at pickup."""
        viewer = self._viewer()
        if viewer and viewer.is_rider and pickup.pin_visible(trip):
            return trip.otp
        return None

    def get_driver_location(self, trip) -> dict | None:
        driver = trip.driver
        if driver is None or driver.current_lat is None:
            return None
        return {"lat": driver.current_lat, "lng": driver.current_lng, "heading": driver.heading}

    def get_fare(self, trip) -> dict:
        return FareSerializer(trip.final_fare).data

    @extend_schema_field(RideCheckSerializer(allow_null=True))
    def get_open_ride_check(self, trip) -> dict | None:
        """The "Is everything OK?" question waiting for this viewer, if any."""
        if trip.status != TripStatus.IN_PROGRESS:
            return None
        viewer = self._viewer()
        checks = trip.ride_checks.filter(status=RideCheckStatus.OPEN)
        if viewer and viewer.is_driver:
            checks = checks.filter(
                kind__in=[RideCheckKind.LONG_STOP, RideCheckKind.SIGNAL_LOST],
                driver_ok__isnull=True,
            )
        check = checks.first()
        return RideCheckSerializer(check).data if check else None

    def get_is_favourite_driver(self, trip) -> bool:
        viewer = self._viewer()
        if not (viewer and viewer.is_rider and trip.driver_id):
            return False
        return trip.rider.favourite_drivers.filter(pk=trip.driver_id).exists()

    @extend_schema_field(PointSerializer(allow_null=True))
    def get_stop(self, trip) -> dict | None:
        return services.stop_payload(trip)

    def get_has_rated(self, trip) -> bool:
        viewer = self._viewer()
        if viewer is None or trip.status != TripStatus.COMPLETED:
            return False
        direction = "RIDER_TO_DRIVER" if viewer.is_rider else "DRIVER_TO_RIDER"
        return any(r.direction == direction for r in trip.ratings.all())


class TripRequestSerializer(serializers.Serializer):
    ride_type = serializers.SlugRelatedField(
        slug_field="code", queryset=RideType.objects.filter(is_active=True)
    )
    pickup = PointSerializer()
    dropoff = PointSerializer()
    stop = PointSerializer(required=False, allow_null=True)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    tip = serializers.DecimalField(max_digits=6, decimal_places=2, required=False, default=0)
    boost = serializers.DecimalField(max_digits=6, decimal_places=2, required=False, default=0)
    preferences = serializers.ListField(
        child=serializers.ChoiceField(choices=RidePreference.choices), required=False, default=list
    )
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=20)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class StartSerializer(serializers.Serializer):
    """Either the rider's spoken 4-digit PIN or the QR code scanned from their phone."""

    otp = serializers.RegexField(r"^\d{4}$", required=False)
    qr = serializers.CharField(max_length=80, required=False)

    def validate(self, attrs):
        if not attrs.get("otp") and not attrs.get("qr"):
            raise serializers.ValidationError("Scan the rider's QR code or enter their PIN.")
        return attrs


class FavouriteSerializer(serializers.Serializer):
    favourite = serializers.BooleanField()


class BoostSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=5, decimal_places=2)


class RiderLocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)


class ConfirmCarSerializer(serializers.Serializer):
    is_my_car = serializers.BooleanField()


class TelemetrySerializer(serializers.Serializer):
    harsh_brakes = serializers.IntegerField(min_value=0, default=0)
    harsh_accelerations = serializers.IntegerField(min_value=0, default=0)
    speeding_seconds = serializers.IntegerField(min_value=0, default=0)
    night_distance_km = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=Decimal(0), default=Decimal(0)
    )


class CompleteSerializer(serializers.Serializer):
    actual_distance_km = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=Decimal(0), required=False, allow_null=True
    )
    telemetry = TelemetrySerializer(required=False)


class RateSerializer(serializers.Serializer):
    stars = serializers.IntegerField(min_value=1, max_value=5)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=30), required=False, max_length=6
    )
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TipSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=6, decimal_places=2)
    method = serializers.ChoiceField(
        choices=[PaymentMethod.UPI, PaymentMethod.CARD, PaymentMethod.WALLET]
    )
    payer_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)


class SosSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)


class TripEventSerializer(serializers.ModelSerializer):
    actor = serializers.StringRelatedField()

    class Meta:
        model = TripEvent
        fields = [
            "id",
            "kind",
            "from_status",
            "to_status",
            "actor",
            "message",
            "data",
            "created_at",
        ]


class TripMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripMessage
        fields = ["id", "trip_id", "sender", "body", "created_at"]
        read_only_fields = ["id", "trip_id", "sender", "created_at"]


class TripOfferSerializer(serializers.ModelSerializer):
    driver = serializers.StringRelatedField()

    class Meta:
        model = TripOffer
        fields = [
            "id",
            "driver",
            "status",
            "offered_at",
            "expires_at",
            "responded_at",
            "distance_km",
            "eta_minutes",
            "rank_score",
            "dispatch_mode",
        ]


class LostItemSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    rider_name = serializers.CharField(source="trip.rider.name", read_only=True)

    class Meta:
        model = LostItemReport
        fields = [
            "id",
            "trip_id",
            "trip_number",
            "rider_name",
            "description",
            "status",
            "status_label",
            "driver_note",
            "created_at",
            "updated_at",
        ]


class LostItemRequestSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=300)


class LostItemAnswerSerializer(serializers.Serializer):
    found = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class FareSplitSerializer(serializers.ModelSerializer):
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    rider_name = serializers.CharField(source="trip.rider.name", read_only=True)
    friend_name = serializers.CharField(source="friend.name", read_only=True)
    ride_type = serializers.CharField(source="trip.ride_type.name", read_only=True)
    dropoff_address = serializers.CharField(source="trip.dropoff_address", read_only=True)
    trip_fare = serializers.DecimalField(
        source="trip.fare_total", max_digits=10, decimal_places=2, read_only=True
    )
    completed_at = serializers.DateTimeField(source="trip.completed_at", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    incoming = serializers.SerializerMethodField()

    class Meta:
        model = FareSplit
        fields = [
            "id",
            "trip_id",
            "trip_number",
            "rider_name",
            "friend_name",
            "ride_type",
            "dropoff_address",
            "trip_fare",
            "completed_at",
            "amount",
            "status",
            "status_label",
            "incoming",
            "created_at",
        ]

    def get_incoming(self, split) -> bool:
        """True when the viewer is the friend asked to pay (not the rider who asked)."""
        request = self.context.get("request")
        return bool(request and split.friend.user_id == request.user.pk)


class SplitRequestSerializer(serializers.Serializer):
    phones = serializers.ListField(child=serializers.CharField(max_length=20), min_length=1)


class SplitPaySerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["UPI", "CARD", "WALLET"])
    payer_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)


class TripFilter(django_filters.FilterSet):
    since = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="gte")
    until = django_filters.IsoDateTimeFilter(field_name="requested_at", lookup_expr="lt")
    city = django_filters.CharFilter(field_name="city__slug")
    ride_type = django_filters.CharFilter(field_name="ride_type__code")
    active = django_filters.BooleanFilter(method="filter_active")
    flagged = django_filters.BooleanFilter(method="filter_flagged")

    class Meta:
        model = Trip
        fields = ["status", "payment_method", "payment_status", "driver", "rider"]

    def filter_active(self, queryset, name, value):
        return (
            queryset.filter(status__in=ACTIVE_STATUSES)
            if value
            else queryset.exclude(status__in=ACTIVE_STATUSES)
        )

    def filter_flagged(self, queryset, name, value):
        return queryset.exclude(flags=[]) if value else queryset.filter(flags=[])


RIDER = (
    "list",
    "retrieve",
    "create",
    "active",
    "cancel",
    "rate",
    "tip",
    "sos",
    "events",
    "route",
    "receipt",
    "messages",
    "share",
    "call",
    "start_code",
    "rider_location",
    "confirm_car",
    "invoice",
    "email_invoice",
    "boost",
    "favourite",
    "split",
    "lost_item",
    "lost_item_returned",
    "early_drop",
    "home_safe",
)
DRIVER = (
    "list",
    "retrieve",
    "active",
    "cancel",
    "arrive",
    "start",
    "complete",
    "rate",
    "sos",
    "events",
    "route",
    "messages",
    "call",
    "lost_item",
    "lost_item_answer",
    "lost_item_returned",
)


class TripViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, BaseViewSet
):
    """Trips. Riders book and track theirs, drivers run theirs, staff see everything."""

    queryset = Trip.objects.select_related(
        "ride_type", "city", "rider__user", "driver__user", "vehicle", "promo"
    ).prefetch_related(Prefetch("ratings"))
    serializer_class = TripSerializer
    filterset_class = TripFilter
    search_fields = [
        "trip_number",
        "pickup_address",
        "dropoff_address",
        "rider__user__email",
        "driver__user__email",
    ]
    ordering_fields = ["requested_at", "fare_total", "completed_at"]
    rider_lookup = "rider"
    driver_lookup = "driver"
    rider_actions = RIDER
    driver_actions = DRIVER
    capabilities = {
        "list": Cap.TRIPS_VIEW,
        "retrieve": Cap.TRIPS_VIEW,
        "active": Cap.TRIPS_VIEW,
        "events": Cap.TRIPS_VIEW,
        "offers": Cap.TRIPS_VIEW,
        "route": Cap.TRIPS_VIEW,
        "receipt": Cap.TRIPS_VIEW,
        "invoice": Cap.TRIPS_VIEW,
        "messages": Cap.TRIPS_VIEW,
        "cancel": Cap.TRIPS_MANAGE,
    }

    def get_serializer_class(self):
        return TripRequestSerializer if self.action == "create" else TripSerializer

    def _respond(self, trip, code=status.HTTP_200_OK):
        trip = self.get_queryset().get(pk=trip.pk)
        return Response(
            TripSerializer(trip, context=self.get_serializer_context()).data, status=code
        )

    @extend_schema(request=TripRequestSerializer, responses={201: TripSerializer})
    def create(self, request, *args, **kwargs):
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        trip = services.request_trip(
            rider=request.user.rider_profile,
            ride_type=data["ride_type"],
            pickup=(data["pickup"]["lat"], data["pickup"]["lng"]),
            dropoff=(data["dropoff"]["lat"], data["dropoff"]["lng"]),
            pickup_address=data["pickup"].get("address", ""),
            dropoff_address=data["dropoff"].get("address", ""),
            payment_method=data["payment_method"],
            promo_code=data.get("promo_code", ""),
            stop=(data["stop"]["lat"], data["stop"]["lng"]) if data.get("stop") else None,
            stop_address=(data.get("stop") or {}).get("address", ""),
            tip=data.get("tip") or 0,
            preferences=data.get("preferences") or [],
            boost=data.get("boost") or 0,
        )
        return self._respond(trip, status.HTTP_201_CREATED)

    @extend_schema(responses={200: TripSerializer, 204: None})
    @action(detail=False, methods=["get"])
    def active(self, request):
        """The signed-in rider's or driver's current trip, if any."""
        trip = self.get_queryset().filter(status__in=ACTIVE_STATUSES).first()
        if trip is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(TripSerializer(trip, context=self.get_serializer_context()).data)

    @extend_schema(request=CancelSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = services.cancel_trip(
            self.get_object(), user=request.user, reason=serializer.validated_data.get("reason", "")
        )
        return self._respond(trip)

    def _driver(self, request) -> DriverProfile:
        return request.user.driver_profile

    @extend_schema(request=None, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def arrive(self, request, pk=None):
        return self._respond(services.mark_arrived(self.get_object(), driver=self._driver(request)))

    @extend_schema(request=StartSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        serializer = StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._respond(
            services.start_trip(
                self.get_object(),
                driver=self._driver(request),
                otp=serializer.validated_data.get("otp", ""),
                qr=serializer.validated_data.get("qr", ""),
            )
        )

    @extend_schema(request=CompleteSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        serializer = CompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        trip = services.complete_trip(
            self.get_object(),
            driver=self._driver(request),
            actual_distance_km=data.get("actual_distance_km"),
            telemetry=data.get("telemetry"),
        )
        return self._respond(trip)

    @extend_schema(request=RateSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def rate(self, request, pk=None):
        serializer = RateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = self.get_object()
        services.rate_trip(trip, user=request.user, **serializer.validated_data)
        return self._respond(trip)

    @extend_schema(
        request=TipSerializer,
        responses=TripSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER)],
    )
    @action(detail=True, methods=["post"])
    def tip(self, request, pk=None):
        serializer = TipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = services.tip_driver(
            self.get_object(),
            user=request.user,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            **serializer.validated_data,
        )
        return self._respond(trip)

    @extend_schema(request=SosSerializer, responses={201: IncidentSerializer})
    @action(detail=True, methods=["post"])
    def sos(self, request, pk=None):
        from apps.support.services import raise_sos

        serializer = SosSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = raise_sos(trip=self.get_object(), user=request.user, **serializer.validated_data)
        return Response(IncidentSerializer(incident).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=TripEventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        events = self.get_object().events.select_related("actor")
        if request.user.is_end_user:
            events = events.filter(kind__in=["STATUS", "TIP"])
        return Response(TripEventSerializer(events, many=True).data)

    @extend_schema(methods=["GET"], request=None, responses=TripMessageSerializer(many=True))
    @extend_schema(
        methods=["POST"], request=TripMessageSerializer, responses={201: TripMessageSerializer}
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        """In-trip chat. Staff can read it (for support and safety) but not post."""
        trip = self.get_object()
        if request.method == "POST":
            serializer = TripMessageSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            message = services.send_message(
                trip, user=request.user, body=serializer.validated_data["body"]
            )
            return Response(TripMessageSerializer(message).data, status=status.HTTP_201_CREATED)
        return Response(TripMessageSerializer(trip.messages.all(), many=True).data)

    @extend_schema(request=None, responses=TripSerializer)
    @action(detail=True, methods=["post"], url_path="early-drop")
    def early_drop(self, request, pk=None):
        """Night Safe ride: the rider confirms the driver may end the trip before the drop."""
        return self._respond(safety.confirm_early_drop(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=TripSerializer)
    @action(detail=True, methods=["post"], url_path="home-safe")
    def home_safe(self, request, pk=None):
        """ "I'm home safe": tells the trusted contacts who followed the ride."""
        return self._respond(safety.home_safe(self.get_object(), user=request.user))

    @extend_schema(request=LostItemRequestSerializer, responses=LostItemSerializer)
    @action(detail=True, methods=["get", "post"], url_path="lost-item")
    def lost_item(self, request, pk=None):
        """Report an item left in the car (rider, POST) or see the report (GET)."""
        trip = self.get_object()
        if request.method == "POST":
            serializer = LostItemRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            item = lost_items.report(trip, user=request.user, **serializer.validated_data)
            return Response(LostItemSerializer(item).data, status=status.HTTP_201_CREATED)
        item = LostItemReport.objects.filter(trip=trip).first()
        if item is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(LostItemSerializer(item).data)

    @extend_schema(request=LostItemAnswerSerializer, responses=LostItemSerializer)
    @action(detail=True, methods=["post"], url_path="lost-item/answer")
    def lost_item_answer(self, request, pk=None):
        serializer = LostItemAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = lost_items.driver_answer(
            self._lost_item(), user=request.user, **serializer.validated_data
        )
        return Response(LostItemSerializer(item).data)

    @extend_schema(request=None, responses=LostItemSerializer)
    @action(detail=True, methods=["post"], url_path="lost-item/returned")
    def lost_item_returned(self, request, pk=None):
        item = lost_items.mark_returned(self._lost_item(), user=request.user)
        return Response(LostItemSerializer(item).data)

    def _lost_item(self) -> LostItemReport:
        item = LostItemReport.objects.filter(trip=self.get_object()).first()
        if item is None:
            raise ActionNotPermitted("No lost item was reported for this ride.")
        return item

    @extend_schema(request=SplitRequestSerializer, responses=FareSplitSerializer(many=True))
    @action(detail=True, methods=["get", "post"])
    def split(self, request, pk=None):
        """Split this ride's fare with friends (POST) or see who has paid (GET)."""
        trip = self.get_object()
        if request.method == "POST":
            serializer = SplitRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            splits.request_split(
                trip, user=request.user, phones=serializer.validated_data["phones"]
            )
        rows = trip.splits.select_related("friend__user", "trip__rider__user", "trip__ride_type")
        return Response(FareSplitSerializer(rows, many=True).data)

    @extend_schema(request=FavouriteSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def favourite(self, request, pk=None):
        """Save (or unsave) this trip's driver: offered your rides first when nearby."""
        serializer = FavouriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = services.set_favourite(
            self.get_object(), user=request.user, favourite=serializer.validated_data["favourite"]
        )
        return Response({"favourite": saved})

    @extend_schema(request=BoostSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"])
    def boost(self, request, pk=None):
        """Add ₹10/20/30/50 to find a driver faster (100% to the driver)."""
        serializer = BoostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = services.boost_trip(
            self.get_object(), user=request.user, amount=serializer.validated_data["amount"]
        )
        return self._respond(trip)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"], url_path="start-code")
    def start_code(self, request, pk=None):
        """The rotating QR code the driver scans to start the trip (rider only)."""
        trip = self.get_object()
        if not (request.user.is_rider and pickup.pin_visible(trip)):
            raise ActionNotPermitted("The code appears when your driver is close.")
        code, expires_in = pickup.start_code(trip)
        return Response({"code": code, "expires_in": expires_in})

    @extend_schema(request=RiderLocationSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="rider-location")
    def rider_location(self, request, pk=None):
        """The rider's phone location during pickup and the ride (safety checks only)."""
        serializer = RiderLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = pickup.record_rider_location(
            self.get_object(), user=request.user, **serializer.validated_data
        )
        return Response({"tracked": result.tracked, "separated": result.separated})

    @extend_schema(request=ConfirmCarSerializer, responses=TripSerializer)
    @action(detail=True, methods=["post"], url_path="confirm-car")
    def confirm_car(self, request, pk=None):
        """'Is this your car?': yes records it; no alerts the safety desk."""
        serializer = ConfirmCarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = pickup.confirm_car(
            self.get_object(), user=request.user, is_my_car=serializer.validated_data["is_my_car"]
        )
        return self._respond(trip)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def call(self, request, pk=None):
        """Call the other party through a masked number (Exotel), or a demo explanation."""
        result = calls.call_other_party(self.get_object(), user=request.user)
        return Response({"mode": result.mode, "message": result.message})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def share(self, request, pk=None):
        """A link family and friends can open (no login) to follow the ride live."""
        token = services.share_trip(self.get_object(), user=request.user)
        return Response({"token": token, "path": f"/track/{token}"})

    @extend_schema(responses=TripOfferSerializer(many=True))
    @action(detail=True, methods=["get"])
    def offers(self, request, pk=None):
        return Response(
            TripOfferSerializer(
                self.get_object().offers.select_related("driver__user"), many=True
            ).data
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def route(self, request, pk=None):
        return Response(services.trip_route(self.get_object()))

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        trip = self.get_object()
        if trip.status != TripStatus.COMPLETED:
            raise ActionNotPermitted("Receipts are available for completed trips.")
        response = HttpResponse(render_receipt(trip), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{trip.trip_number}.pdf"'
        return response

    def _paid_trip(self) -> Trip:
        trip = self.get_object()
        if trip.status != TripStatus.COMPLETED or trip.payment_status != TripPaymentStatus.PAID:
            raise ActionNotPermitted("The invoice is ready once the fare has been paid.")
        invoices.ensure_number(trip)
        return trip

    @extend_schema(responses={(200, "text/html"): str})
    @action(detail=True, methods=["get"])
    def invoice(self, request, pk=None):
        """The invoice exactly as emailed, to view in the app."""
        return HttpResponse(invoices.render_html(self._paid_trip()), content_type="text/html")

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="email-invoice")
    def email_invoice(self, request, pk=None):
        """Send the invoice to the rider's email again (a few times a day at most)."""
        trip = self._paid_trip()
        if not invoices.can_email(trip):
            raise BusinessRuleViolation("Add an email address in your account to get invoices.")
        today = timezone.now() - timedelta(days=1)
        if trip.events.filter(kind="INVOICE_RESENT", created_at__gte=today).count() >= 3:
            raise ConflictError(
                "The invoice was already sent a few times today. Check your spam folder."
            )
        invoices.send(trip, force=True)
        services.record_event(trip, "INVOICE_RESENT", actor=request.user, message="Invoice emailed")
        return Response({"sent_to": trip.rider.user.email})


class DispatchSweepView(ContextBindingMixin, APIView):
    """Run one dispatcher tick now (normally Celery beat runs it every 10 seconds)."""

    permission_classes = [CapabilityPermission]
    capabilities = {"post": Cap.DISPATCH_RUN}

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT}, tags=["operations"])
    def post(self, request):
        return Response(dispatch.sweep())


class LiveOpsView(ContextBindingMixin, APIView):
    """Everything on the live operations map: online drivers and active trips."""

    permission_classes = [CapabilityPermission]
    capabilities = {"get": Cap.TRIPS_VIEW}

    @extend_schema(
        parameters=[OpenApiParameter("city", str, description="City slug")],
        responses={200: OpenApiTypes.OBJECT},
        tags=["operations"],
    )
    def get(self, request):
        city = request.query_params.get("city")
        drivers = DriverProfile.objects.exclude(availability=Availability.OFFLINE).filter(
            current_lat__isnull=False
        )
        trips = Trip.objects.filter(status__in=ACTIVE_STATUSES).select_related(
            "ride_type", "driver__user"
        )
        if city:
            drivers = drivers.filter(city__slug=city)
            trips = trips.filter(city__slug=city)
        return Response(
            {
                "time": timezone.now(),
                "drivers": [
                    {
                        "id": d.pk,
                        "name": d.name,
                        "lat": d.current_lat,
                        "lng": d.current_lng,
                        "heading": d.heading,
                        "availability": d.availability,
                        "ride_type": next(
                            (v.ride_type.code for v in d.vehicles.all() if v.is_active), None
                        ),
                    }
                    for d in drivers.select_related("user").prefetch_related("vehicles__ride_type")[
                        :2000
                    ]
                ],
                "trips": [
                    {
                        "id": t.pk,
                        "trip_number": t.trip_number,
                        "status": t.status,
                        "ride_type": t.ride_type.code,
                        "pickup": [t.pickup_lat, t.pickup_lng],
                        "dropoff": [t.dropoff_lat, t.dropoff_lng],
                        "driver_id": t.driver_id,
                        "requested_at": t.requested_at,
                    }
                    for t in trips[:1000]
                ],
            }
        )


class NearbyDriversView(ContextBindingMixin, APIView):
    """Available cars near a point, for the rider's map. Positions are rounded for privacy."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", float, required=True),
            OpenApiParameter("lng", float, required=True),
        ],
        responses={200: OpenApiTypes.OBJECT},
        tags=["fares"],
    )
    def get(self, request):
        from apps.drivers.services import nearby_available_drivers

        try:
            lat, lng = float(request.query_params["lat"]), float(request.query_params["lng"])
        except (KeyError, ValueError):
            return Response({"drivers": []})
        drivers = nearby_available_drivers(lat=lat, lng=lng, radius_km=3, limit=15)
        # An opaque per-day key lets the app animate each car between refreshes without
        # learning which driver it is (or following them across days).
        day = timezone.localdate().isoformat()
        vehicles = {
            v.driver_id: v.ride_type.code
            for v in Vehicle.objects.filter(driver__in=drivers, is_active=True).select_related(
                "ride_type"
            )
        }
        return Response(
            {
                "drivers": [
                    {
                        "key": salted_hmac("nearby-car", f"{d.pk}:{day}").hexdigest()[:12],
                        "lat": round(d.current_lat, 4),
                        "lng": round(d.current_lng, 4),
                        "heading": d.heading,
                        "ride_type": vehicles.get(d.pk),
                    }
                    for d in drivers
                ]
            }
        )


class SharedTripView(APIView):
    """Public, read-only view of a shared trip (the "follow my ride" page)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["trips"])
    def get(self, request, token):
        view = services.shared_trip_view(token)
        if view is None:
            raise NotFound("This link has expired or doesn't exist.")
        return Response(view)


class ScheduledRideSerializer(serializers.ModelSerializer):
    ride_type = serializers.CharField(source="ride_type.code")
    ride_type_name = serializers.CharField(source="ride_type.name")
    status_label = serializers.CharField(source="get_status_display")
    pickup = serializers.SerializerMethodField()
    dropoff = serializers.SerializerMethodField()
    stop = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledRide
        fields = [
            "id",
            "ride_type",
            "ride_type_name",
            "pickup",
            "dropoff",
            "stop",
            "payment_method",
            "promo_code",
            "scheduled_for",
            "quoted_fare",
            "status",
            "status_label",
            "trip_id",
            "failure_reason",
            "created_at",
        ]

    @extend_schema_field(PointSerializer)
    def get_pickup(self, ride) -> dict:
        return {"lat": ride.pickup_lat, "lng": ride.pickup_lng, "address": ride.pickup_address}

    @extend_schema_field(PointSerializer)
    def get_dropoff(self, ride) -> dict:
        return {"lat": ride.dropoff_lat, "lng": ride.dropoff_lng, "address": ride.dropoff_address}

    @extend_schema_field(PointSerializer(allow_null=True))
    def get_stop(self, ride) -> dict | None:
        return services.stop_payload(ride)


class ScheduleRequestSerializer(TripRequestSerializer):
    scheduled_for = serializers.DateTimeField()


class ScheduledRideViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, BaseViewSet
):
    """Rides booked for later. A few minutes before pickup each becomes a normal trip."""

    queryset = ScheduledRide.objects.select_related("ride_type", "rider__user", "trip")
    serializer_class = ScheduledRideSerializer
    filterset_fields = ["status"]
    ordering_fields = ["scheduled_for", "created_at"]
    rider_lookup = "rider"
    rider_actions = ("list", "retrieve", "create", "cancel")
    capabilities = {"list": Cap.TRIPS_VIEW, "retrieve": Cap.TRIPS_VIEW}

    @extend_schema(request=ScheduleRequestSerializer, responses={201: ScheduledRideSerializer})
    def create(self, request, *args, **kwargs):
        serializer = ScheduleRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ride = services.schedule_ride(
            rider=request.user.rider_profile,
            ride_type=data["ride_type"],
            pickup=(data["pickup"]["lat"], data["pickup"]["lng"]),
            dropoff=(data["dropoff"]["lat"], data["dropoff"]["lng"]),
            pickup_address=data["pickup"].get("address", ""),
            dropoff_address=data["dropoff"].get("address", ""),
            payment_method=data["payment_method"],
            promo_code=data.get("promo_code", ""),
            stop=(data["stop"]["lat"], data["stop"]["lng"]) if data.get("stop") else None,
            stop_address=(data.get("stop") or {}).get("address", ""),
            scheduled_for=data["scheduled_for"],
        )
        return Response(ScheduledRideSerializer(ride).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=ScheduledRideSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ride = services.cancel_scheduled_ride(self.get_object(), user=request.user)
        return Response(ScheduledRideSerializer(ride).data)


class FareSplitViewSet(mixins.ListModelMixin, BaseViewSet):
    """Fare-split requests: ones sent to me (to pay or decline) and ones I sent (to track)."""

    serializer_class = FareSplitSerializer
    rider_actions = ("list", "pay", "decline", "cancel")
    filterset_fields = ["status"]

    def get_queryset(self):
        from django.db.models import Q

        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_rider:
            return FareSplit.objects.none()
        me = self.request.user
        return FareSplit.objects.select_related(
            "trip__rider__user", "trip__ride_type", "friend__user"
        ).filter(Q(friend__user=me) | Q(trip__rider__user=me))

    @extend_schema(request=SplitPaySerializer, responses=FareSplitSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        serializer = SplitPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        split = splits.pay_split(self.get_object(), user=request.user, **serializer.validated_data)
        return Response(FareSplitSerializer(split).data)

    @extend_schema(request=None, responses=FareSplitSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return Response(
            FareSplitSerializer(splits.decline_split(self.get_object(), user=request.user)).data
        )

    @extend_schema(request=None, responses=FareSplitSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(
            FareSplitSerializer(splits.cancel_split(self.get_object(), user=request.user)).data
        )


class RideCheckViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Ride Checks: "Is everything OK?" questions raised automatically during trips."""

    queryset = RideCheck.objects.select_related("trip__rider__user", "trip__driver__user").order_by(
        "status", "-created_at"
    )
    serializer_class = RideCheckSerializer
    filterset_fields = ["status", "kind", "trip"]
    rider_lookup = "trip__rider"
    driver_lookup = "trip__driver"
    rider_actions = ("list", "retrieve", "answer")
    driver_actions = ("list", "retrieve", "answer")
    capabilities = {"list": Cap.SAFETY_MANAGE, "retrieve": Cap.SAFETY_MANAGE}

    @extend_schema(request=RideCheckAnswerSerializer, responses=RideCheckSerializer)
    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        serializer = RideCheckAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        check = safety.answer(self.get_object(), user=request.user, **serializer.validated_data)
        return Response(RideCheckSerializer(check).data)
