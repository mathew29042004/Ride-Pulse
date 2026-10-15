"""Platform health API: the event outbox, webhooks (and a demo receiver) and security events."""

import hmac
import json

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from . import outbox, security
from .models import DeliveryStatus, WebhookDelivery, WebhookEndpoint


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
