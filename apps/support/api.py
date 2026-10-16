import django_filters
from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from . import services
from .models import (
    OPEN_TICKET_STATUSES,
    SafetyIncident,
    SafetyRecording,
    SupportTicket,
    TicketMessage,
)


class TicketMessageSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField()
    author_is_staff = serializers.BooleanField(source="author.is_staff_member", read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "author", "author_is_staff", "body", "is_internal", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    raised_by = serializers.StringRelatedField()
    assigned_to = serializers.StringRelatedField()
    trip_number = serializers.CharField(source="trip.trip_number", default=None, read_only=True)
    messages = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "raised_by",
            "trip",
            "trip_number",
            "category",
            "priority",
            "status",
            "subject",
            "description",
            "assigned_to",
            "sla_due_at",
            "escalated",
            "resolved_at",
            "resolution",
            "refund_amount",
            "created_at",
            "messages",
            "rating",
        ]

    def get_rating(self, ticket) -> int | None:
        rating = getattr(ticket, "rating", None)
        return rating.score if rating else None

    def get_messages(self, ticket) -> list[dict]:
        request = self.context.get("request")
        messages = ticket.messages.all()  # prefetched with their authors by the view
        if request is None or request.user.is_end_user:
            messages = [m for m in messages if not m.is_internal]
        return TicketMessageSerializer(messages, many=True).data


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ["category", "subject", "description", "trip"]


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField()
    internal = serializers.BooleanField(default=False)


class ResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField()
    refund_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=0
    )


class AssignSerializer(serializers.Serializer):
    agent = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.filter(is_active=True)
    )


class TicketFilter(django_filters.FilterSet):
    open = django_filters.BooleanFilter(method="filter_open")
    mine = django_filters.BooleanFilter(method="filter_mine")

    class Meta:
        model = SupportTicket
        fields = ["status", "priority", "category", "escalated", "assigned_to"]

    def filter_open(self, queryset, name, value):
        lookup = {"status__in": OPEN_TICKET_STATUSES}
        return queryset.filter(**lookup) if value else queryset.exclude(**lookup)

    def filter_mine(self, queryset, name, value):
        return queryset.filter(assigned_to=self.request.user) if value else queryset


END_USER_ACTIONS = ("list", "retrieve", "create", "reply")


class TicketViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, BaseViewSet
):
    """Help tickets. Riders and drivers see their own; support staff work the queue."""

    queryset = SupportTicket.objects.select_related(
        "raised_by", "assigned_to", "trip", "rating"
    ).prefetch_related(
        Prefetch("messages", queryset=TicketMessage.objects.select_related("author"))
    )
    serializer_class = TicketSerializer
    filterset_class = TicketFilter
    search_fields = ["ticket_number", "subject", "raised_by__email", "trip__trip_number"]
    ordering_fields = ["created_at", "sla_due_at", "priority"]
    rider_actions = END_USER_ACTIONS
    driver_actions = END_USER_ACTIONS
    capabilities = {
        "list": Cap.SUPPORT_VIEW,
        "retrieve": Cap.SUPPORT_VIEW,
        "create": Cap.SUPPORT_VIEW,
        "reply": Cap.SUPPORT_VIEW,
        "assign": Cap.SUPPORT_MANAGE,
        "resolve": Cap.SUPPORT_MANAGE,
    }

    def scope_queryset(self, queryset):
        user = self.request.user
        return queryset.filter(raised_by=user) if user.is_end_user else queryset

    @extend_schema(request=TicketCreateSerializer, responses={201: TicketSerializer})
    def create(self, request, *args, **kwargs):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.open_ticket(user=request.user, **serializer.validated_data)
        return Response(
            TicketSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ReplySerializer, responses=TicketSerializer)
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = self.get_object()
        services.reply(ticket, author=request.user, **serializer.validated_data)
        return Response(TicketSerializer(ticket, context={"request": request}).data)

    @extend_schema(request=AssignSerializer, responses=TicketSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.assign(
            self.get_object(), agent=serializer.validated_data["agent"], actor=request.user
        )
        return Response(TicketSerializer(ticket, context={"request": request}).data)

    @extend_schema(request=ResolveSerializer, responses=TicketSerializer)
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.resolve(
            self.get_object(), actor=request.user, **serializer.validated_data
        )
        return Response(TicketSerializer(ticket, context={"request": request}).data)


class IncidentSerializer(serializers.ModelSerializer):
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    raised_by = serializers.StringRelatedField()
    acknowledged_by = serializers.StringRelatedField()

    class Meta:
        model = SafetyIncident
        fields = [
            "id",
            "incident_number",
            "trip",
            "trip_number",
            "raised_by",
            "lat",
            "lng",
            "note",
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "resolved_at",
            "resolution_note",
            "ticket",
            "created_at",
        ]


class IncidentResolveSerializer(serializers.Serializer):
    note = serializers.CharField()


class IncidentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """SOS alerts for the safety desk."""

    queryset = SafetyIncident.objects.select_related("trip", "raised_by", "acknowledged_by")
    serializer_class = IncidentSerializer
    filterset_fields = ["status"]
    capabilities = {"*": Cap.SAFETY_MANAGE}

    @extend_schema(request=None, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return Response(
            IncidentSerializer(
                services.acknowledge_incident(self.get_object(), actor=request.user)
            ).data
        )

    @extend_schema(request=IncidentResolveSerializer, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        serializer = IncidentResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = services.resolve_incident(
            get_object_or_404(SafetyIncident, pk=pk),
            actor=request.user,
            note=serializer.validated_data["note"],
        )
        return Response(IncidentSerializer(incident).data)


class RecordingSerializer(serializers.ModelSerializer):
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True)

    class Meta:
        model = SafetyRecording
        fields = [
            "id",
            "trip_id",
            "trip_number",
            "ticket_id",
            "uploaded_by_name",
            "mime_type",
            "duration_seconds",
            "size_bytes",
            "created_at",
        ]


class RecordingViewSet(mixins.ListModelMixin, BaseViewSet):
    """Trip audio recordings shared with the safety team. Playing one is audited."""

    queryset = SafetyRecording.objects.select_related("trip", "uploaded_by")
    serializer_class = RecordingSerializer
    filterset_fields = ["ticket", "trip"]
    capabilities = {"list": Cap.SAFETY_MANAGE, "audio": Cap.SAFETY_MANAGE}

    @extend_schema(responses={(200, "audio/webm"): bytes})
    @action(detail=True, methods=["get"])
    def audio(self, request, pk=None):
        from django.http import HttpResponse

        from .recordings import play

        audio, mime = play(get_object_or_404(SafetyRecording, pk=pk), actor=request.user)
        response = HttpResponse(audio, content_type=mime)
        response["Cache-Control"] = "no-store"
        return response
