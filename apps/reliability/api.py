"""Platform health API: the event outbox, webhooks (and a demo receiver) and security events."""

import contextlib
import hmac
import json

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.accounts.two_factor import coverage as two_factor_coverage
from apps.core.api import BaseViewSet

from . import jobs, outbox, security
from .models import (
    ChiefUpdate,
    CommandAlert,
    CommandOrder,
    DecisionRequest,
    Delegation,
    DeliveryStatus,
    Incident,
    OrderKind,
    WeatherAlert,
    WeatherLevel,
    WebhookDelivery,
    WebhookEndpoint,
)


class EndpointSerializer(serializers.ModelSerializer):
    delivered = serializers.IntegerField(read_only=True)
    failing = serializers.IntegerField(read_only=True)
    dead = serializers.IntegerField(read_only=True)

    class Meta:
        model = WebhookEndpoint
        fields = [
            "id",
            "name",
            "url",
            "topics",
            "is_active",
            "consecutive_failures",
            "disabled_reason",
            "delivered",
            "failing",
            "dead",
            "created_at",
        ]


class CreateEndpointSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    url = serializers.URLField(max_length=300)
    topics = serializers.ListField(
        child=serializers.ChoiceField(choices=list(outbox.TOPICS)), required=False
    )


class UnlockSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PlatformViewSet(BaseViewSet):
    """Event outbox health, webhook endpoints and deliveries, and the security log."""

    capabilities = {"*": Cap.AUDIT_VIEW}
    queryset = WebhookEndpoint.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def health(self, request):
        return Response(
            {
                "outbox": outbox.health(),
                "topics": outbox.TOPICS,
                "security": security.overview(),
                "echo_received": cache.get("webhooks:echo", [])[:10],
                "jobs": jobs.jobs_overview(),
                "two_factor": two_factor_coverage(),
                "speed": {**jobs.latency_by_route(), **jobs.slow_overview()},
            }
        )

    @extend_schema(methods=["GET"], responses=EndpointSerializer(many=True))
    @extend_schema(
        methods=["POST"], request=CreateEndpointSerializer, responses={201: OpenApiTypes.OBJECT}
    )
    @action(detail=False, methods=["get", "post"])
    def webhooks(self, request):
        from django.db.models import Count, Q

        if request.method == "POST":
            data = CreateEndpointSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            endpoint = WebhookEndpoint.objects.create(
                name=data.validated_data["name"],
                url=data.validated_data["url"],
                topics=data.validated_data.get("topics", []),
                secret=outbox.new_secret(),
                created_by=request.user,
            )
            # The signing secret is shown once, at creation, like Stripe and GitHub do.
            return Response(
                {**EndpointSerializer(endpoint).data, "secret": endpoint.secret},
                status=status.HTTP_201_CREATED,
            )
        rows = WebhookEndpoint.objects.annotate(
            delivered=Count("deliveries", filter=Q(deliveries__status=DeliveryStatus.DELIVERED)),
            failing=Count("deliveries", filter=Q(deliveries__status=DeliveryStatus.RETRYING)),
            dead=Count("deliveries", filter=Q(deliveries__status=DeliveryStatus.DEAD)),
        )
        return Response(EndpointSerializer(rows, many=True).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"webhooks/(?P<endpoint_id>\d+)/replay")
    def replay_dead(self, request, endpoint_id=None):
        endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id)
        dead = WebhookDelivery.objects.filter(endpoint=endpoint, status=DeliveryStatus.DEAD)
        count = 0
        for delivery in dead:
            outbox.replay(delivery)
            count += 1
        if not endpoint.is_active:
            WebhookEndpoint.objects.filter(pk=endpoint.pk).update(
                is_active=True, consecutive_failures=0, disabled_reason=""
            )
        return Response({"replayed": count})

    @extend_schema(request=UnlockSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def unlock(self, request):
        data = UnlockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        security.unlock(data.validated_data["email"], actor=request.user)
        return Response(security.overview())


class WebhookEchoView(APIView):
    """Demo receiver: checks the signature like a real partner would and remembers the last
    events, so the outbox can be watched end to end without an outside service."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT, 401: None})
    def post(self, request):
        body = request.body
        signature = request.headers.get("X-RidePulse-Signature", "")
        endpoints = WebhookEndpoint.objects.filter(url__endswith="/webhooks/echo/")
        if not any(hmac.compare_digest(outbox.sign(e.secret, body), signature) for e in endpoints):
            return Response({"error": "bad signature"}, status=status.HTTP_401_UNAUTHORIZED)
        event = json.loads(body)
        seen = cache.get("webhooks:echo", [])
        if not any(e["id"] == event["id"] for e in seen):  # idempotent: duplicates are ignored
            seen.insert(0, {"id": event["id"], "topic": event["topic"], "at": event["created_at"]})
        cache.set("webhooks:echo", seen[:50], 3600)
        return Response({"ok": True})


# --- Incidents and the status page --------------------------------------------------------------


class OpenIncidentSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    severity = serializers.ChoiceField(choices=["MINOR", "MAJOR", "CRITICAL"])
    components = serializers.ListField(child=serializers.CharField(max_length=13), max_length=6)
    public_message = serializers.CharField(max_length=240)


class IncidentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["INVESTIGATING", "IDENTIFIED", "MONITORING", "RESOLVED"]
    )
    message = serializers.CharField(max_length=500)
    public_message = serializers.CharField(required=False, allow_blank=True, max_length=240)


class IncidentReviewSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=4000)
    root_cause = serializers.CharField(max_length=2000)
    actions = serializers.ListField(child=serializers.DictField(), required=False, max_length=10)


def _incident_row(i) -> dict:
    return {
        "id": i.pk,
        "number": i.number,
        "war_room": getattr(getattr(i, "war_room", None), "pk", None),
        "title": i.title,
        "severity": i.severity,
        "severity_label": i.get_severity_display(),
        "status": i.status,
        "status_label": i.get_status_display(),
        "components": i.components,
        "public_message": i.public_message,
        "started_at": i.started_at,
        "resolved_at": i.resolved_at,
        "minutes": round(((i.resolved_at or timezone.now()) - i.started_at).total_seconds() / 60),
        "summary": i.summary,
        "root_cause": i.root_cause,
        "reviewed_at": i.reviewed_at,
        "updates": [
            {
                "status_label": u.get_status_display(),
                "message": u.message,
                "at": u.at,
                "by": u.by.get_full_name() if u.by_id else None,
            }
            for u in i.updates.all()
        ],
    }


class IncidentViewSet(BaseViewSet):
    capabilities = {"list": Cap.TRIPS_VIEW, "*": Cap.TRIPS_MANAGE}
    queryset = Incident.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        rows = Incident.objects.prefetch_related("updates__by")[:50]
        return Response([_incident_row(i) for i in rows])

    @extend_schema(request=OpenIncidentSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from . import incidents

        data = OpenIncidentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        incident = incidents.open_incident(user=request.user, **data.validated_data)
        return Response(_incident_row(incident), status=status.HTTP_201_CREATED)

    @extend_schema(request=IncidentUpdateSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        from . import incidents

        data = IncidentUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        incident = incidents.update(
            get_object_or_404(Incident, pk=pk), user=request.user, **data.validated_data
        )
        return Response(_incident_row(incident))

    @extend_schema(request=IncidentReviewSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        from . import incidents

        data = IncidentReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        incident, tasks = incidents.review(
            get_object_or_404(Incident, pk=pk),
            user=request.user,
            summary=data.validated_data["summary"],
            root_cause=data.validated_data["root_cause"],
            actions=data.validated_data.get("actions", []),
        )
        return Response({**_incident_row(incident), "tasks": [t.number for t in tasks]})


class StatusPageView(APIView):
    """Public: the status of each part of Ride Pulse, open incidents and the last 14 days."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["status"])
    def get(self, request):
        from . import incidents

        return Response(incidents.status_page())


class StatusBannerView(APIView):
    """For the signed-in rider or driver: the open incident that affects their app, if any."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["status"])
    def get(self, request):
        from . import incidents
        from .fallbacks import active

        return Response(
            {"banner": incidents.banner_for(request.user), "fallbacks": sorted(active())}
        )


class StartWeatherSerializer(serializers.Serializer):
    city = serializers.IntegerField()
    level = serializers.ChoiceField(choices=WeatherLevel.choices)
    hours = serializers.IntegerField(min_value=1, max_value=72, default=6)
    zones = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    message = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")


class WeatherViewSet(BaseViewSet):
    """Monsoon / flood mode per city (see ``reliability.weather``)."""

    capabilities = {"list": Cap.PRICING_VIEW, "*": Cap.PRICING_MANAGE}
    queryset = WeatherAlert.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="weather_alerts_list")
    def list(self, request):
        from apps.geo.models import City

        from . import weather

        alerts = WeatherAlert.objects.select_related("city", "created_by").prefetch_related(
            "zones"
        )[:50]
        cities = City.objects.filter(is_active=True).prefetch_related("zones").order_by("name")
        return Response(
            {
                "alerts": [weather.row(a) for a in alerts],
                "cities": [
                    {
                        "id": c.pk,
                        "name": c.name,
                        "zones": [{"id": z.pk, "name": z.name} for z in c.zones.all()],
                    }
                    for c in cities
                ],
            }
        )

    @extend_schema(request=StartWeatherSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from apps.geo.models import City, Zone

        from . import weather

        data = StartWeatherSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        city = get_object_or_404(City, pk=v["city"])
        alert = weather.start(
            city=city,
            level=v["level"],
            user=request.user,
            hours=v["hours"],
            zones=Zone.objects.filter(pk__in=v["zones"], city=city),
            message=v["message"],
        )
        return Response(weather.row(alert), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        from . import weather

        return Response(weather.row(weather.end(get_object_or_404(WeatherAlert, pk=pk))))


class BackupViewSet(BaseViewSet):
    """Ops → Backups: nightly backups and restore drills; run either now."""

    capabilities = {"list": Cap.AUDIT_VIEW, "*": Cap.USERS_MANAGE}
    queryset = Incident.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="backups_overview")
    def list(self, request):
        from . import backups

        return Response(backups.overview())

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="run")
    def run_backup(self, request):
        from . import backups

        with contextlib.suppress(RuntimeError):  # a failed run is recorded and shown
            backups.backup(user=request.user)
        return Response(backups.overview())

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def drill(self, request):
        from . import backups

        with contextlib.suppress(RuntimeError):
            backups.restore_drill(user=request.user)
        return Response(backups.overview())


class IssueOrderSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=OrderKind.choices)
    city = serializers.IntegerField(required=False, allow_null=True, default=None)
    vehicle_code = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(max_length=240)
    hours = serializers.IntegerField(min_value=1, max_value=72, default=2)
    confirm = serializers.BooleanField(default=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ActSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["driver", "rider", "trip"])
    id = serializers.IntegerField()
    action = serializers.ChoiceField(
        choices=["suspend", "reinstate", "offline", "block", "unblock", "cancel"]
    )
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")


class DelegateSerializer(serializers.Serializer):
    to = serializers.IntegerField()
    hours = serializers.IntegerField(min_value=1, max_value=72, default=8)
    reason = serializers.CharField(max_length=240)


class BroadcastSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    body = serializers.CharField(max_length=2000)
    audiences = serializers.ListField(child=serializers.CharField())


class CommandViewSet(BaseViewSet):
    """The commander's command centre (see ``reliability.command``)."""

    capabilities = {"*": Cap.COMMAND}
    queryset = CommandOrder.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="command_overview")
    def list(self, request):
        from . import command

        return Response(command.overview())

    @extend_schema(request=IssueOrderSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from apps.geo.models import City

        from . import command

        data = IssueOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        city = get_object_or_404(City, pk=v["city"]) if v["city"] else None
        order = command.issue(
            user=request.user,
            kind=v["kind"],
            reason=v["reason"],
            city=city,
            vehicle_code=v["vehicle_code"],
            hours=v["hours"],
            confirm=v["confirm"],
            starts_at=v["starts_at"],
        )
        return Response(command.row(order), status=status.HTTP_201_CREATED)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def target(self, request):
        """Set this month's completion target for a city."""
        from apps.geo.models import City

        from . import command

        t = command.set_target(
            user=request.user,
            city=get_object_or_404(City, pk=int(request.data.get("city", 0))),
            completion_pct=int(request.data.get("completion_pct", 80)),
            max_wait_min=int(request.data.get("max_wait_min", 6)),
        )
        return Response({"city": t.city_id, "completion_pct": t.completion_pct})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def lift(self, request, pk=None):
        from . import command

        order = command.lift(get_object_or_404(CommandOrder, pk=pk), user=request.user)
        return Response(command.row(order))

    @extend_schema(request=BroadcastSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def broadcast(self, request):
        from . import command

        data = BroadcastSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        sent = command.broadcast(user=request.user, **data.validated_data)
        return Response({"sent": sent})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"alerts/(?P<alert_id>\d+)/acknowledge")
    def acknowledge(self, request, alert_id=None):
        from . import command

        alert = get_object_or_404(CommandAlert, pk=alert_id)
        return Response(command.alert_row(command.acknowledge(alert, user=request.user)))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def people(self, request):
        from . import command

        return Response({"results": command.find_people(request.query_params.get("q", ""))})

    @extend_schema(request=ActSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def act(self, request):
        from . import command

        data = ActSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(command.act(user=request.user, **data.validated_data))

    @extend_schema(request=DelegateSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def delegate(self, request):
        from apps.accounts.models import User

        from . import command

        data = DelegateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        d = command.delegate(
            user=request.user,
            to=get_object_or_404(User, pk=v["to"]),
            hours=v["hours"],
            reason=v["reason"],
        )
        return Response(command.delegation_row(d), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"delegations/(?P<delegation_id>\d+)/revoke")
    def revoke(self, request, delegation_id=None):
        from . import command

        d = get_object_or_404(Delegation, pk=delegation_id)
        return Response(command.delegation_row(command.revoke(d, user=request.user)))


class UpdateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["UPDATE", "BRIEFING", "ESCALATION"], default="UPDATE")
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")


class AskSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    detail = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    order = serializers.DictField(required=False, default=dict)


class EscalateSerializer(serializers.Serializer):
    alert = serializers.IntegerField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class TextSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ChiefDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class BriefViewSet(BaseViewSet):
    """The chief of staff's desk: send the chief updates, briefings and escalations; ask for
    decisions (see ``reliability.briefing``)."""

    capabilities = {"*": Cap.BRIEF}
    queryset = ChiefUpdate.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="brief_desk")
    def list(self, request):
        from . import briefing

        return Response(briefing.sender_view(request.user))

    @extend_schema(request=UpdateSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from . import briefing

        data = UpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        u = briefing.send_update(user=request.user, **data.validated_data)
        return Response(briefing.update_row(u), status=status.HTTP_201_CREATED)

    @extend_schema(request=AskSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def ask(self, request):
        from . import briefing

        data = AskSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        d = briefing.ask(user=request.user, **data.validated_data)
        return Response(briefing.decision_row(d), status=status.HTTP_201_CREATED)

    @extend_schema(request=EscalateSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def escalate(self, request):
        from . import briefing

        data = EscalateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        u = briefing.escalate_alert(
            data.validated_data["alert"], user=request.user, note=data.validated_data["note"]
        )
        return Response(briefing.update_row(u), status=status.HTTP_201_CREATED)


class ChiefInboxViewSet(BaseViewSet):
    """The chief's inbox: updates from the chief of staff, and decisions to make."""

    capabilities = {"*": Cap.COMMAND}
    queryset = ChiefUpdate.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="chief_inbox")
    def list(self, request):
        from . import briefing

        return Response(briefing.chief_inbox(request.query_params.get("source", "")))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def question(self, request):
        """Ask the chief of staff's desk a question; the answer comes from live numbers."""
        from . import briefing

        u = briefing.answer(str(request.data.get("question", "")), user=request.user)
        return Response(briefing.update_row(u))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def thank(self, request):
        """Thank this week's best city, support agent or driver."""
        from . import command

        line = command.thank(
            user=request.user,
            kind=str(request.data.get("kind", "")),
            note=str(request.data.get("note", "")),
        )
        return Response({"posted": line})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def read(self, request):
        from . import briefing

        return Response({"marked": briefing.mark_read(request.user)})

    @extend_schema(request=TextSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"updates/(?P<update_id>\d+)/reply")
    def reply(self, request, update_id=None):
        from . import briefing

        data = TextSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        u = briefing.reply(
            get_object_or_404(ChiefUpdate, pk=update_id),
            user=request.user,
            text=data.validated_data["text"],
        )
        return Response(briefing.update_row(u))

    @extend_schema(request=ChiefDecisionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"decisions/(?P<decision_id>\d+)/decide")
    def decide(self, request, decision_id=None):
        from . import briefing

        data = ChiefDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        d = briefing.decide(
            get_object_or_404(DecisionRequest, pk=decision_id),
            user=request.user,
            **data.validated_data,
        )
        return Response(briefing.decision_row(d))
