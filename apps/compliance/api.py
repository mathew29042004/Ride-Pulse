"""Ops: the Aggregator Guidelines dashboard per state, and recording driver checks."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.drivers.models import DriverProfile

from . import checks


class PoliceSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=40)


class ComplianceViewSet(BaseViewSet):
    capabilities = {
        "*": Cap.DRIVERS_VIEW,
        "police": Cap.DRIVERS_VERIFY,
        "induction": Cap.DRIVERS_VERIFY,
    }
    queryset = DriverProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        return Response(checks.overview())

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path=r"states/(?P<state>[^/]+)")
    def state(self, request, state=None):
        return Response(checks.state_report(state))

    @extend_schema(request=PoliceSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"drivers/(?P<driver_id>\d+)/police")
    def police(self, request, driver_id=None):
        data = PoliceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        driver = checks.record_police_verification(
            get_object_or_404(DriverProfile, pk=driver_id),
            reference=data.validated_data["reference"],
            user=request.user,
        )
        return Response({"police_verified_on": driver.police_verified_on})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"drivers/(?P<driver_id>\d+)/induction")
    def induction(self, request, driver_id=None):
        driver = checks.record_induction(get_object_or_404(DriverProfile, pk=driver_id))
        return Response({"induction_trained_on": driver.induction_trained_on})
