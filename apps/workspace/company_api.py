"""Company portal API: the public website (``/api/v1/public/company/…``, no sign-in) and the
employee intranet (``/api/v1/company/…``, staff)."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.core.exceptions import ActionNotPermitted

from . import company


class ApplySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    profile_url = serializers.URLField(required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class ContactSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    topic = serializers.CharField(max_length=12, required=False, default="GENERAL")
    message = serializers.CharField(max_length=3000)


class FormThrottle(AnonRateThrottle):
    rate = "10/hour"


class PublicCompanyView(APIView):
    """Public: about Ride Pulse (live numbers, leaders, cities) and open roles."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["company"])
    def get(self, request):
        return Response(
            {**company.about(), "jobs": [company.job_row(j) for j in company.open_jobs()]}
        )


class PublicJobView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_throttles(self):
        return [FormThrottle()] if self.request.method == "POST" else super().get_throttles()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["company"])
    def get(self, request, job_id):
        job = get_object_or_404(company.JobOpening, pk=job_id, is_open=True)
        return Response(company.job_row(job, full=True))

    @extend_schema(request=ApplySerializer, responses={201: OpenApiTypes.OBJECT}, tags=["company"])
    def post(self, request, job_id):
        job = get_object_or_404(company.JobOpening, pk=job_id)
        data = ApplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        company.apply(job, **data.validated_data)
        return Response({"applied": True}, status=status.HTTP_201_CREATED)


class PublicContactView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FormThrottle]

    @extend_schema(
        request=ContactSerializer, responses={201: OpenApiTypes.OBJECT}, tags=["company"]
    )
    def post(self, request):
        data = ContactSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        company.contact(**data.validated_data)
        return Response({"sent": True}, status=status.HTTP_201_CREATED)


class MessageSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=6000)


class ReferSerializer(ApplySerializer):
    job = serializers.IntegerField()


class IntranetViewSet(BaseViewSet):
    """The employee intranet."""

    capabilities = {"*": Cap.WORK_USE}
    queryset = company.JobOpening.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="intranet_home")
    def list(self, request):
        return Response(company.intranet(request.user))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def directory(self, request):
        return Response(
            {
                "people": company.directory(
                    request.query_params.get("q", ""), request.query_params.get("department", "")
                )
            }
        )

    @extend_schema(request=MessageSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def message(self, request):
        if not request.user.has_capability(Cap.COMMAND):
            raise ActionNotPermitted("Company-wide messages come from the commander.")
        data = MessageSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        m = company.post_message(request.user, **data.validated_data)
        return Response({"id": m.pk}, status=status.HTTP_201_CREATED)

    @extend_schema(request=ReferSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def refer(self, request):
        data = ReferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        job = get_object_or_404(company.JobOpening, pk=v.pop("job"))
        company.apply(job, referred_by=request.user, **v)
        return Response({"referred": True}, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def applications(self, request):
        if not request.user.has_capability(Cap.PEOPLE_MANAGE):
            raise ActionNotPermitted("Applications are for HR.")
        return Response({"applications": company.applications()})

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"applications/(?P<application_id>\d+)/status")
    def application_status(self, request, application_id=None):
        if not request.user.has_capability(Cap.PEOPLE_MANAGE):
            raise ActionNotPermitted("Applications are for HR.")
        a = company.set_status(
            get_object_or_404(company.JobApplication, pk=application_id),
            user=request.user,
            status=str(request.data.get("status", "")),
        )
        return Response({"status": a.status})


class ApprovalsViewSet(BaseViewSet):
    """Everything waiting on me, from every corner of the console."""

    capabilities = {"*": Cap.WORK_USE}
    queryset = company.JobOpening.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="approvals_inbox")
    def list(self, request):
        from .approvals import pending

        items = pending(request.user)
        return Response({"count": len(items), "items": items})


class SearchViewSet(BaseViewSet):
    capabilities = {"*": Cap.WORK_USE}
    queryset = company.JobOpening.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="search_everything")
    def list(self, request):
        from .search import search

        return Response({"results": search(request.user, request.query_params.get("q", ""))})
