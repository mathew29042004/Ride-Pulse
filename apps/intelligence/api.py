"""Ops intelligence API: /intel/alerts, /intel/briefing, /intel/demand, /intel/fraud and the
driver app's hot zones."""

from datetime import date, timedelta

from django.core.cache import cache
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from . import briefing, demand, fraud
from .models import FraudCase, OpsAlert


class AlertSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source="city.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", default=None, read_only=True)
    task_status = serializers.CharField(source="task.status", default=None, read_only=True)

    class Meta:
        model = OpsAlert
        fields = [
            "id",
            "kind",
            "kind_label",
            "city",
            "city_name",
            "severity",
            "title",
            "detail",
            "metrics",
            "status",
            "owner",
            "owner_name",
            "task",
            "task_status",
            "created_at",
            "resolved_at",
        ]


class AlertViewSet(mixins.ListModelMixin, BaseViewSet):
    """Automatic alerts (``?status=OPEN|RESOLVED``); each one created a task for its owner."""

    serializer_class = AlertSerializer
    capabilities = {"*": Cap.REPORTS_VIEW}
    filterset_fields = ["status", "kind", "city"]

    def get_queryset(self):
        return OpsAlert.objects.select_related("city", "owner", "task")


class FraudCaseSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    driver_name = serializers.CharField(source="driver.name", default=None, read_only=True)
    rider_name = serializers.CharField(
        source="rider.user.get_full_name", default=None, read_only=True
    )
    city_name = serializers.CharField(source="city.name", default=None, read_only=True)
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.get_full_name", default=None, read_only=True
    )

    class Meta:
        model = FraudCase
        fields = [
            "id",
            "number",
            "kind",
            "kind_label",
            "driver",
            "driver_name",
            "rider",
            "rider_name",
            "city_name",
            "score",
            "summary",
            "evidence",
            "trip_ids",
            "status",
            "status_label",
            "reviewed_by_name",
            "reviewed_at",
            "review_note",
            "action_taken",
            "created_at",
        ]


class FraudReviewSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    action = serializers.ChoiceField(choices=fraud.ACTIONS, default="NONE")


class FraudCaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """The fraud review queue (``?status=OPEN|CONFIRMED|DISMISSED``)."""

    serializer_class = FraudCaseSerializer
    capabilities = {"*": Cap.FRAUD_REVIEW}
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return FraudCase.objects.select_related(
            "driver__user", "rider__user", "city", "reviewed_by"
        )

    @extend_schema(request=FraudReviewSerializer, responses=FraudCaseSerializer)
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        data = FraudReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        case = fraud.review(self.get_object(), user=request.user, **data.validated_data)
        return Response(FraudCaseSerializer(case).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(fraud.summary())


class CityEventSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import CityEvent

        model = CityEvent
        fields = [
            "city",
            "name",
            "kind",
            "venue",
            "lat",
            "lng",
            "starts_at",
            "ends_at",
            "expected_attendance",
        ]

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "The event must end after it starts."})
        return attrs


class WinBackSerializer(serializers.Serializer):
    rider_ids = serializers.ListField(child=serializers.IntegerField(), max_length=500)
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=300)


class InsightsViewSet(BaseViewSet):
    """The morning briefing, the next-hour demand forecast and the driver app's hot zones."""

    capabilities = {
        "briefing": Cap.REPORTS_VIEW,
        "demand": Cap.REPORTS_VIEW,
        "outlook": Cap.REPORTS_VIEW,
        "events": Cap.PRICING_MANAGE,
        "models": Cap.REPORTS_VIEW,
        "win_back": Cap.PROMOS_MANAGE,
        "surge_policy": Cap.PRICING_VIEW,
    }
    driver_actions = ("hot_zones",)
    rider_actions = ("nearby",)

    @extend_schema(
        parameters=[OpenApiParameter("day", OpenApiTypes.DATE, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def briefing(self, request):
        """A day's briefing (default: yesterday), written on demand if the 8 am job hasn't run."""
        from .models import DailyBriefing

        raw = request.query_params.get("day")
        try:
            day = date.fromisoformat(raw) if raw else timezone.localdate() - timedelta(days=1)
        except ValueError:
            day = timezone.localdate() - timedelta(days=1)
        found = DailyBriefing.objects.filter(day=day).first()
        if found is None and day < timezone.localdate():
            found = briefing.generate(day=day, send=False)
        days = list(DailyBriefing.objects.values_list("day", flat=True)[:14])
        return Response({"briefing": found.data if found else None, "available": days})

    @extend_schema(
        parameters=[OpenApiParameter("city", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def demand(self, request):
        city = request.query_params.get("city")
        city_id = int(city) if city and city.isdigit() else None
        accuracy = demand.cached_accuracy(city_id)
        if accuracy is None:
            # The backtest replays 72 hours: computed once here, then kept fresh in the
            # background (every 30 minutes) so the page never waits for it again.
            accuracy = demand.refresh_accuracy(city_id)
        result = demand.forecast(city_id=city_id)
        result["accuracy"] = accuracy
        return Response(result)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def hot_zones(self, request):
        from apps.experiments.services import enabled

        if not enabled("driver-hot-zones", request.user):
            return Response([])
        return Response(demand.hot_zones_for(request.user.driver_profile))

    @extend_schema(
        parameters=[OpenApiParameter("lat", float), OpenApiParameter("lng", float)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def nearby(self, request):
        """Rider Home: rain and big events near the rider today."""
        from apps.experiments.services import enabled

        from . import context

        if not enabled("rider-weather-alerts", request.user):
            return Response({"weather": None, "events": [], "messages": []})
        try:
            lat, lng = float(request.query_params["lat"]), float(request.query_params["lng"])
        except (KeyError, ValueError):
            return Response({"weather": None, "events": [], "messages": []})
        return Response(context.for_rider(lat, lng))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def outlook(self, request):
        """Ops: weather in every city and upcoming events."""
        from . import context

        return Response(context.overview())

    @extend_schema(request=CityEventSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def events(self, request):
        data = CityEventSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        event = data.save(created_by=request.user)
        return Response({"id": event.pk}, status=201)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def models(self, request):
        """Model cards (what each model predicts and how well) and riders at risk of churning."""
        from . import ml

        return Response({"cards": ml.model_cards(), "at_risk": ml.at_risk(limit=40)})

    @extend_schema(request=WinBackSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def win_back(self, request):
        from . import ml

        data = WinBackSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response({"sent": ml.win_back(**data.validated_data)})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"], url_path="surge-policy")
    def surge_policy(self, request):
        """Replay recorded demand and supply under candidate surge settings (GET), or turn the
        recommendation into a draft A/B test (POST)."""

        from . import surge_policy

        result = cache.get("intel:surge-policy")
        if result is None:
            result = surge_policy.optimise()
            cache.set("intel:surge-policy", result, 600)
        if request.method == "POST":
            if not request.user.has_capability(Cap.EXPERIMENTS_MANAGE):
                from apps.core.exceptions import ActionNotPermitted

                raise ActionNotPermitted("Only experiment owners can propose a test.")
            experiment = surge_policy.propose_experiment(result, user=request.user)
            return Response({"experiment": experiment.key if experiment else None, **result})
        return Response(result)
