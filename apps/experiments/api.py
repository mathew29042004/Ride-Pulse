"""Feature flags and A/B tests for ops: ``ops/experiments/…``."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from . import services
from .models import Experiment, FeatureFlag


class FlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = [
            "key",
            "description",
            "enabled",
            "rollout_percent",
            "allow_user_ids",
            "updated_at",
        ]


class FlagUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    rollout_percent = serializers.IntegerField(required=False, min_value=0, max_value=100)


class ExperimentSerializer(serializers.ModelSerializer):
    results = serializers.SerializerMethodField()

    class Meta:
        model = Experiment
        fields = [
            "key",
            "name",
            "hypothesis",
            "status",
            "treatment_percent",
            "treatment_config",
            "primary_metric",
            "minimum_effect",
            "started_at",
            "stopped_at",
            "decision",
            "results",
        ]

    def get_results(self, experiment) -> dict:
        return services.results(experiment)


class StopSerializer(serializers.Serializer):
    decision = serializers.CharField(max_length=200)


class ExperimentsOpsViewSet(BaseViewSet):
    capabilities = {"*": Cap.EXPERIMENTS_MANAGE}
    queryset = FeatureFlag.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def overview(self, request):
        return Response(
            {
                "flags": FlagSerializer(FeatureFlag.objects.all(), many=True).data,
                "experiments": ExperimentSerializer(Experiment.objects.all(), many=True).data,
            }
        )

    @extend_schema(request=FlagUpdateSerializer, responses=FlagSerializer)
    @action(detail=False, methods=["post"], url_path=r"flags/(?P<key>[\w-]+)")
    def flag(self, request, key=None):
        data = FlagUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        get_object_or_404(FeatureFlag, key=key)
        flag = services.set_flag(
            key,
            actor=request.user,
            enabled_=data.validated_data.get("enabled"),
            rollout=data.validated_data.get("rollout_percent"),
        )
        return Response(FlagSerializer(flag).data)

    @extend_schema(request=None, responses=ExperimentSerializer)
    @action(detail=False, methods=["post"], url_path=r"(?P<key>[\w-]+)/start")
    def start(self, request, key=None):
        experiment = services.start(get_object_or_404(Experiment, key=key))
        return Response(ExperimentSerializer(experiment).data)

    @extend_schema(request=StopSerializer, responses=ExperimentSerializer)
    @action(detail=False, methods=["post"], url_path=r"(?P<key>[\w-]+)/stop")
    def stop(self, request, key=None):
        data = StopSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        experiment = services.stop(get_object_or_404(Experiment, key=key), **data.validated_data)
        return Response(ExperimentSerializer(experiment).data, status=status.HTTP_200_OK)
