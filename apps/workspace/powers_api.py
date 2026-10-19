"""Ops → Powers: each specialist role's actions (see ``workspace.powers``)."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.core.exceptions import ActionNotPermitted

from . import powers

SPECIALIST = (
    Cap.REFUND_APPROVE,
    Cap.SAFETY_BAN,
    Cap.LEGAL_HOLD,
    Cap.DISPATCH_ASSIGN,
    Cap.PEOPLE_MANAGE,
)


class RefundDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class PersonReasonSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    reason = serializers.CharField(max_length=300)


class LegalHoldSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    case_reference = serializers.CharField(max_length=80)
    reason = serializers.CharField(max_length=300)


class ManualAssignSerializer(serializers.Serializer):
    trip = serializers.IntegerField()
    driver = serializers.IntegerField()


class StaffTransferSerializer(serializers.Serializer):
    employee = serializers.IntegerField()
    manager = serializers.IntegerField(required=False, allow_null=True, default=None)
    city = serializers.IntegerField(required=False, allow_null=True, default=None)
    role = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(max_length=300)


class PowersViewSet(BaseViewSet):
    capabilities = {
        "list": Cap.TEAM_VIEW,
        "people": Cap.TEAM_VIEW,
        "decide_refund": Cap.REFUND_APPROVE,
        "ban": Cap.SAFETY_BAN,
        "lift_ban": Cap.SAFETY_BAN,
        "hold": Cap.LEGAL_HOLD,
        "release_hold": Cap.LEGAL_HOLD,
        "drivers_for": Cap.DISPATCH_ASSIGN,
        "assign": Cap.DISPATCH_ASSIGN,
        "transfer": Cap.PEOPLE_MANAGE,
    }
    queryset = powers.RefundApproval.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="powers_overview")
    def list(self, request):
        if not any(request.user.has_capability(c) for c in SPECIALIST):
            raise ActionNotPermitted("Your role has no special powers here.")
        return Response(powers.overview(request.user))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def people(self, request):
        """Find a person (any role) by email, phone or name, for the forms on this page."""
        from django.db.models import Q

        from apps.accounts.models import User

        q = request.query_params.get("q", "").strip()
        if len(q) < 3:
            return Response({"results": []})
        users = User.objects.filter(
            Q(email__icontains=q)
            | Q(phone__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        ).select_related("staff_profile")[:10]
        return Response(
            {
                "results": [
                    {
                        "id": u.pk,
                        "name": u.get_full_name(),
                        "email": u.email,
                        "role": u.role,
                        "role_label": u.get_role_display(),
                        "staff_profile": getattr(getattr(u, "staff_profile", None), "pk", None),
                        "on_hold": powers.on_hold(u) is not None,
                    }
                    for u in users
                ]
            }
        )

    @extend_schema(request=RefundDecisionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"refunds/(?P<refund_id>\d+)/decide")
    def decide_refund(self, request, refund_id=None):
        data = RefundDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        r = powers.decide_refund(
            get_object_or_404(powers.RefundApproval, pk=refund_id),
            actor=request.user,
            **data.validated_data,
        )
        return Response({"status": r.status})

    def _user(self, pk):
        from apps.accounts.models import User

        return get_object_or_404(User, pk=pk)

    @extend_schema(request=PersonReasonSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def ban(self, request):
        data = PersonReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rows = powers.ban(
            self._user(data.validated_data["user"]),
            actor=request.user,
            reason=data.validated_data["reason"],
        )
        return Response({"banned": len(rows)})

    @extend_schema(request=PersonReasonSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="lift-ban")
    def lift_ban(self, request):
        data = PersonReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        n = powers.lift_ban(
            self._user(data.validated_data["user"]),
            actor=request.user,
            reason=data.validated_data["reason"],
        )
        return Response({"lifted": n})

    @extend_schema(request=LegalHoldSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def hold(self, request):
        data = LegalHoldSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        h = powers.place_hold(
            self._user(v["user"]),
            actor=request.user,
            case_reference=v["case_reference"],
            reason=v["reason"],
        )
        return Response({"id": h.pk}, status=201)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"holds/(?P<hold_id>\d+)/release")
    def release_hold(self, request, hold_id=None):
        powers.release_hold(get_object_or_404(powers.LegalHold, pk=hold_id), actor=request.user)
        return Response({"released": True})

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path=r"trips/(?P<trip_id>\d+)/drivers")
    def drivers_for(self, request, trip_id=None):
        from apps.rides.models import Trip

        return Response({"drivers": powers.nearby_drivers(get_object_or_404(Trip, pk=trip_id))})

    @extend_schema(request=ManualAssignSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def assign(self, request):
        from apps.drivers.models import DriverProfile
        from apps.rides.models import Trip

        data = ManualAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        offer = powers.assign_to(
            get_object_or_404(Trip, pk=data.validated_data["trip"]),
            get_object_or_404(DriverProfile, pk=data.validated_data["driver"]),
            actor=request.user,
        )
        return Response({"offer": offer.pk})

    @extend_schema(request=StaffTransferSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def transfer(self, request):
        from apps.accounts.models import StaffProfile
        from apps.geo.models import City

        data = StaffTransferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        profile = powers.transfer(
            self._user(v["employee"]),
            actor=request.user,
            manager=get_object_or_404(StaffProfile, pk=v["manager"]) if v["manager"] else None,
            city=get_object_or_404(City, pk=v["city"]) if v["city"] else None,
            role=v["role"],
            reason=v["reason"],
        )
        return Response({"employee": profile.user_id})
