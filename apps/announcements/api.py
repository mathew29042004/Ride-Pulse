"""Announcements: ops publish and see read rates; everyone reads their own."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.geo.models import City

from . import services
from .models import Announcement


class PublishSerializer(serializers.Serializer):
    audience = serializers.ChoiceField(choices=["DRIVERS", "RIDERS", "STAFF"])
    state = serializers.CharField(required=False, allow_blank=True, max_length=60)
    city = serializers.SlugRelatedField(
        slug_field="slug", queryset=City.objects.all(), required=False, allow_null=True
    )
    important = serializers.BooleanField(default=False)
    text = serializers.DictField()


class AnnouncementViewSet(BaseViewSet):
    capabilities = {
        "list": Cap.ANNOUNCE,
        "create": Cap.ANNOUNCE,
        "mine": Cap.WORK_USE,
        "read": Cap.WORK_USE,
    }
    rider_actions = ("mine", "read")
    driver_actions = ("mine", "read")
    queryset = Announcement.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        return Response(services.report())

    @extend_schema(request=PublishSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        data = PublishSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        announcement = services.publish(user=request.user, **data.validated_data)
        return Response(
            {"id": announcement.pk, "recipients": announcement.recipients},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def mine(self, request):
        return Response(services.inbox(request.user))

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        get_object_or_404(Announcement, pk=pk)
        services.mark_read(request.user, int(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
