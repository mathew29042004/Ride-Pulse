"""Driver business API.

* ``driver/biz/…`` (drivers): weekly statements and PDFs, quests, EV battery and chargers,
  vehicle care and the airport queue.
* ``fleet/…`` (fleet owners): their portal; owners can also log services and let drivers go.
* ``ops/fleet/…`` (fleet executives and up): fleet owners, quests, vehicle upkeep, airport
  queues, the EV network and the quarterly TDS report.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation
from apps.drivers.api import IsDriver
from apps.drivers.models import DriverProfile, Vehicle, VehicleCondition
from apps.geo.models import City
from apps.pricing.models import RideType

from . import airport, ev, maintenance, owners, quests, statements
from .models import (
    DriverStatement,
    FleetOwner,
    IssueKind,
    IssueSeverity,
    IssueSource,
    Quest,
    ServiceKind,
)

# --- Drivers ---------------------------------------------------------------------------------


class StatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverStatement
        exclude = ["driver"]


class BatterySerializer(serializers.Serializer):
    percent = serializers.IntegerField(min_value=0, max_value=100)


class PartSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class ServiceSerializer(serializers.Serializer):
    odometer_km = serializers.IntegerField(required=False, min_value=0)
    workshop = serializers.CharField(required=False, allow_blank=True, max_length=120)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=255)
    kind = serializers.ChoiceField(choices=ServiceKind.choices, required=False)
    parts = PartSerializer(many=True, required=False)
    labour_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False
    )
    invoice_number = serializers.CharField(required=False, allow_blank=True, max_length=40)
    resolves = serializers.ListField(child=serializers.IntegerField(), required=False)


class InspectionSerializer(serializers.Serializer):
    items = serializers.DictField(child=serializers.BooleanField())


class IssueSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=IssueKind.choices)
    severity = serializers.ChoiceField(choices=IssueSeverity.choices, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=300)


class ConditionSerializer(serializers.Serializer):
    condition = serializers.ChoiceField(choices=VehicleCondition.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class DriverBusinessViewSet(ContextBindingMixin, GenericViewSet):
    """The driver's business: statements, quests, EV, vehicle care, airport queue."""

    permission_classes = [IsDriver]
    serializer_class = StatementSerializer
    queryset = DriverStatement.objects.none()

    @property
    def driver(self) -> DriverProfile:
        return (
            DriverProfile.objects.select_related("user", "city")
            .prefetch_related("vehicles__ride_type")
            .get(user=self.request.user)
        )

    @extend_schema(responses=StatementSerializer(many=True))
    @action(detail=False, methods=["get"])
    def statements(self, request):
        rows = DriverStatement.objects.filter(driver__user=request.user)[:26]
        return Response(
            {
                "pan_on_file": statements.pan_on_file(self.driver),
                "statements": StatementSerializer(rows, many=True).data,
            }
        )

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=False, methods=["get"], url_path=r"statements/(?P<number>[A-Z0-9-]+)/pdf")
    def statement_pdf(self, request, number=None):
        statement = get_object_or_404(DriverStatement, driver__user=request.user, number=number)
        response = HttpResponse(statements.render_pdf(statement), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{statement.number}.pdf"'
        return response

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="quests")
    def my_quests(self, request):
        return Response(quests.for_driver(self.driver))

    @extend_schema(request=BatterySerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"], url_path="ev")
    def electric(self, request):
        driver = self.driver
        if request.method == "POST":
            data = BatterySerializer(data=request.data)
            data.is_valid(raise_exception=True)
            ev.set_battery(driver, data.validated_data["percent"])
            driver = self.driver
        return Response(ev.my_ev(driver))

    @extend_schema(request=ServiceSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"], url_path="vehicle")
    def vehicle_care(self, request):
        vehicle = self.driver.active_vehicle
        if vehicle is None:
            return Response(None)
        if request.method == "POST":
            data = ServiceSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            maintenance.record_service(vehicle, user=request.user, **data.validated_data)
        return Response(self._care(vehicle))

    def _care(self, vehicle):
        health = maintenance.health_of(vehicle)
        health["history"] = maintenance.history(vehicle, limit=10)
        health["costs"] = maintenance.costs(vehicle)
        health["checklist"] = maintenance.CHECKLIST
        health["critical_items"] = list(maintenance.CRITICAL_ITEMS)
        return health

    @extend_schema(request=InspectionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="vehicle/check")
    def vehicle_check(self, request):
        """The daily walk-round. A failed brake, tyre, light or belt takes the car off the road."""
        vehicle = self._vehicle()
        data = InspectionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        maintenance.submit_inspection(vehicle, driver=self.driver, **data.validated_data)
        return Response(self._care(vehicle))

    @extend_schema(request=IssueSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="vehicle/issue")
    def vehicle_issue(self, request):
        """Report a fault or a breakdown (a breakdown mid-ride gets the rider a new car)."""
        vehicle = self._vehicle()
        data = IssueSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        maintenance.report_issue(
            vehicle, user=request.user, source=IssueSource.DRIVER, **data.validated_data
        )
        return Response(self._care(vehicle))

    def _vehicle(self):
        vehicle = self.driver.active_vehicle
        if vehicle is None:
            raise BusinessRuleViolation("Add a vehicle first.")
        return vehicle

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="airport")
    def airport_spot(self, request):
        return Response(airport.my_spot(self.driver))


# --- Fleet owners ----------------------------------------------------------------------------


class OwnerDriverSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField()


class OwnerServiceSerializer(ServiceSerializer):
    vehicle_id = serializers.IntegerField()


class FleetOwnerPortalViewSet(BaseViewSet):
    """A fleet owner's own portal."""

    capabilities = {"*": Cap.FLEET_OWN}

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        return Response(owners.dashboard(owners.owner_for(request.user)))

    @extend_schema(request=OwnerDriverSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def release(self, request):
        owner = owners.owner_for(request.user)
        data = OwnerDriverSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        driver = get_object_or_404(DriverProfile, pk=data.validated_data["driver_id"])
        owners.remove_driver(owner, driver)
        return Response(owners.dashboard(owner))

    @extend_schema(request=OwnerServiceSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def service(self, request):
        owner = owners.owner_for(request.user)
        data = OwnerServiceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        vehicle = get_object_or_404(
            Vehicle.objects.select_related("ride_type"), pk=fields.pop("vehicle_id"), owner=owner
        )
        maintenance.record_service(vehicle, user=request.user, **fields)
        return Response(owners.dashboard(owner))

    @extend_schema(request=ConditionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"vehicles/(?P<vehicle_id>\d+)/condition")
    def condition(self, request, vehicle_id=None):
        """Send a car to the workshop, or bring it back once nothing critical is open."""
        owner = owners.owner_for(request.user)
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id, owner=owner)
        data = ConditionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        maintenance.set_condition(
            vehicle, data.validated_data["condition"], note=data.validated_data.get("note", "")
        )
        return Response(owners.dashboard(owner))


# --- Ops -------------------------------------------------------------------------------------


class FleetOwnerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.get_full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True)
    drivers = serializers.IntegerField(read_only=True)
    vehicles_count = serializers.IntegerField(read_only=True)
    manager_name = serializers.CharField(
        source="account_manager.user.get_full_name", default=None, read_only=True
    )

    class Meta:
        model = FleetOwner
        fields = [
            "id",
            "company_name",
            "name",
            "email",
            "city",
            "city_name",
            "gstin",
            "share_percent",
            "drivers",
            "vehicles_count",
            "manager_name",
            "is_active",
        ]


class CreateOwnerSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=120)
    first_name = serializers.CharField(max_length=60)
    last_name = serializers.CharField(max_length=60, allow_blank=True, required=False)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    city = serializers.PrimaryKeyRelatedField(queryset=City.objects.all())
    gstin = serializers.CharField(max_length=15, required=False, allow_blank=True)
    share_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class QuestSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source="city.name", default=None, read_only=True)
    ride_type_codes = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Quest
        fields = [
            "id",
            "number",
            "name",
            "city",
            "city_name",
            "state",
            "ride_type_codes",
            "starts_at",
            "ends_at",
            "tiers",
            "peak_hours_only",
            "min_rating",
            "budget",
            "spent",
            "status",
            "stats",
        ]

    def get_ride_type_codes(self, quest) -> list[str]:
        return [rt.code for rt in quest.ride_types.all()]

    def get_stats(self, quest) -> dict:
        return quests.stats(quest)


class CreateQuestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    city = serializers.PrimaryKeyRelatedField(
        queryset=City.objects.all(), required=False, allow_null=True
    )
    state = serializers.CharField(max_length=60, required=False, allow_blank=True)
    ride_types = serializers.SlugRelatedField(
        slug_field="code", queryset=RideType.objects.all(), many=True, required=False
    )
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    tiers = serializers.ListField(child=serializers.ListField(min_length=2, max_length=2))
    budget = serializers.DecimalField(max_digits=12, decimal_places=2)
    peak_hours_only = serializers.BooleanField(default=False)
    min_rating = serializers.DecimalField(
        max_digits=3, decimal_places=2, required=False, allow_null=True
    )
    launch = serializers.BooleanField(default=True)


class FleetOpsViewSet(BaseViewSet):
    """Fleet owners, quests, vehicle upkeep, airports, EVs and TDS for the ops team."""

    capabilities = {"*": Cap.FLEET_MANAGE, "tds": Cap.PAYMENTS_VIEW}
    queryset = FleetOwner.objects.none()

    def _city(self, request):
        city = request.query_params.get("city")
        return int(city) if city and city.isdigit() else None

    @extend_schema(
        methods=["GET"],
        parameters=[OpenApiParameter("city", int, required=False)],
        responses=FleetOwnerSerializer(many=True),
    )
    @extend_schema(methods=["POST"], request=CreateOwnerSerializer, responses=FleetOwnerSerializer)
    @action(detail=False, methods=["get", "post"])
    def owners(self, request):
        from django.db.models import Count, Q

        if request.method == "POST":
            data = CreateOwnerSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            fields = dict(data.validated_data)
            fields.setdefault("last_name", "")
            fields["account_manager"] = getattr(request.user, "staff_profile", None)
            owner = owners.create_owner(**fields)
            return Response(FleetOwnerSerializer(owner).data, status=status.HTTP_201_CREATED)
        rows = FleetOwner.objects.select_related("user", "city", "account_manager__user").annotate(
            drivers=Count(
                "memberships", filter=Q(memberships__left_at__isnull=True), distinct=True
            ),
            vehicles_count=Count("vehicles", filter=Q(vehicles__is_active=True), distinct=True),
        )
        if self._city(request):
            rows = rows.filter(city_id=self._city(request))
        return Response(FleetOwnerSerializer(rows, many=True).data)

    @extend_schema(request=OwnerDriverSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"owners/(?P<owner_id>\d+)/drivers")
    def owner_drivers(self, request, owner_id=None):
        owner = get_object_or_404(FleetOwner, pk=owner_id)
        data = OwnerDriverSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        driver = get_object_or_404(DriverProfile, pk=data.validated_data["driver_id"])
        owners.add_driver(owner, driver)
        return Response(owners.dashboard(owner))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path=r"owners/(?P<owner_id>\d+)/dashboard")
    def owner_dashboard(self, request, owner_id=None):
        return Response(owners.dashboard(get_object_or_404(FleetOwner, pk=owner_id)))

    @extend_schema(methods=["GET"], responses=QuestSerializer(many=True))
    @extend_schema(methods=["POST"], request=CreateQuestSerializer, responses=QuestSerializer)
    @action(detail=False, methods=["get", "post"], url_path="quests")
    def quest_list(self, request):
        if request.method == "POST":
            data = CreateQuestSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            quest = quests.create_quest(user=request.user, **data.validated_data)
            return Response(QuestSerializer(quest).data, status=status.HTTP_201_CREATED)
        rows = Quest.objects.select_related("city").prefetch_related("ride_types")
        state = request.query_params.get("status")
        if state:
            rows = rows.filter(status=state)
        return Response(QuestSerializer(rows[:100], many=True).data)

    @extend_schema(request=None, responses=QuestSerializer, operation_id="ops_fleet_quest_action")
    @action(
        detail=False, methods=["post"], url_path=r"quests/(?P<quest_id>\d+)/(?P<verb>launch|cancel)"
    )
    def quest_action(self, request, quest_id=None, verb=None):
        quest = get_object_or_404(Quest, pk=quest_id)
        quest = (
            quests.launch(quest, user=request.user)
            if verb == "launch"
            else quests.cancel(quest, user=request.user)
        )
        return Response(QuestSerializer(quest).data)

    @extend_schema(
        parameters=[OpenApiParameter("city", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def upkeep(self, request):
        return Response(maintenance.fleet_health(city_id=self._city(request)))

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="ops_fleet_upkeep_vehicle")
    @action(detail=False, methods=["get"], url_path=r"upkeep/(?P<vehicle_id>\d+)")
    def upkeep_vehicle(self, request, vehicle_id=None):
        vehicle = get_object_or_404(Vehicle.objects.select_related("ride_type"), pk=vehicle_id)
        return Response(
            {
                **maintenance.health_of(vehicle),
                "history": maintenance.history(vehicle),
                "costs": maintenance.costs(vehicle),
                "inspections": list(
                    vehicle.inspections.values("inspected_on", "passed", "items")[:14]
                ),
            }
        )

    @extend_schema(request=ConditionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"upkeep/(?P<vehicle_id>\d+)/condition")
    def upkeep_condition(self, request, vehicle_id=None):
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
        data = ConditionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        maintenance.set_condition(
            vehicle, data.validated_data["condition"], note=data.validated_data.get("note", "")
        )
        return Response(maintenance.health_of(vehicle))

    @extend_schema(request=IssueSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"upkeep/(?P<vehicle_id>\d+)/issue")
    def upkeep_issue(self, request, vehicle_id=None):
        vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
        data = IssueSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        maintenance.report_issue(
            vehicle, user=request.user, source=IssueSource.OPS, **data.validated_data
        )
        return Response(maintenance.health_of(vehicle))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def airports(self, request):
        return Response(airport.overview())

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def electric(self, request):
        return Response(ev.overview())

    @extend_schema(
        parameters=[
            OpenApiParameter("year", int, required=False, description="Financial year start"),
            OpenApiParameter("quarter", int, required=False),
            OpenApiParameter("export", str, required=False, description="csv"),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def tds(self, request):
        fy, q = statements.current_quarter(timezone.localdate())
        year = int(request.query_params.get("year") or fy)
        quarter = int(request.query_params.get("quarter") or q)
        if quarter not in (1, 2, 3, 4):
            raise ActionNotPermitted("Quarter is 1-4.")
        report = statements.tds_report(year, quarter)
        if request.query_params.get("export") == "csv":
            import csv
            import io

            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["driver_id", "name", "pan_on_file", "gross_fares", "tds"])
            for row in report["rows"]:
                writer.writerow(
                    [
                        row["driver_id"],
                        row["name"],
                        row["pan_on_file"],
                        row["gross_fares"],
                        row["tds"],
                    ]
                )
            response = HttpResponse(out.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="tds-fy{report["financial_year"]}-q{quarter}.csv"'
            )
            return response
        report["rows"] = report["rows"][:100]
        return Response(report)
