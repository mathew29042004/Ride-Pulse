"""Trust and compliance API.

* ``me/privacy``, ``me/appeals``, ``me/claims``: riders, drivers and fleet owners.
* ``help``: the help centre (anyone signed in), with votes.
* ``tickets/<id>/rate``: CSAT on the person's own resolved ticket.
* ``ops/trust/…``: the privacy queue, appeals, the claims desk, CSAT, saved replies, help
  articles and opted-in offers.
"""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.exceptions import ActionNotPermitted
from apps.reliability.security import client_ip
from apps.rides.models import Trip
from apps.support.models import SupportTicket

from . import appeals, claims, privacy, support_quality
from .models import (
    Appeal,
    AppealSubject,
    Audience,
    ClaimKind,
    ConsentPurpose,
    DataRequest,
    HelpArticle,
    InsuranceClaim,
    Macro,
    RequestKind,
)


class IsEndUser(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_end_user


# --- People's own rights, appeals and claims -------------------------------------------------


class DataRequestSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    download = serializers.SerializerMethodField()

    class Meta:
        model = DataRequest
        fields = [
            "id",
            "number",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "details",
            "due_at",
            "execute_after",
            "outcome",
            "created_at",
            "completed_at",
            "download",
            "user_label",
        ]

    def get_download(self, request) -> bool:
        return bool(request.export_file) and bool(
            request.export_expires_at and request.export_expires_at > timezone.now()
        )


class ConsentSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=ConsentPurpose.choices)
    granted = serializers.BooleanField()


class SubmitRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=RequestKind.choices)
    details = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class AppealSerializer(serializers.ModelSerializer):
    subject_label = serializers.CharField(source="get_subject_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)
    original_decided_by_name = serializers.CharField(
        source="original_decided_by.get_full_name", default=None, read_only=True
    )
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.get_full_name", default=None, read_only=True
    )

    class Meta:
        model = Appeal
        fields = [
            "id",
            "number",
            "subject",
            "subject_label",
            "status",
            "status_label",
            "user_name",
            "original_reason",
            "original_decided_by",
            "original_decided_by_name",
            "statement",
            "due_at",
            "decision_note",
            "reviewed_by_name",
            "created_at",
            "decided_at",
        ]


class SubmitAppealSerializer(serializers.Serializer):
    subject = serializers.ChoiceField(choices=AppealSubject.choices)
    statement = serializers.CharField(max_length=4000)


class ClaimSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    trip_number = serializers.CharField(source="trip.trip_number", read_only=True)
    claimant_name = serializers.CharField(source="claimant.get_full_name", read_only=True)
    documents = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceClaim
        fields = [
            "id",
            "number",
            "trip",
            "trip_number",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "claimant_name",
            "description",
            "happened_at",
            "amount_claimed",
            "amount_approved",
            "insurer_reference",
            "decision_note",
            "created_at",
            "decided_at",
            "paid_at",
            "documents",
        ]

    def get_documents(self, claim) -> list[dict]:
        return [{"id": d.pk, "label": d.label, "url": d.file.url} for d in claim.documents.all()]


class FileClaimSerializer(serializers.Serializer):
    trip = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=ClaimKind.choices)
    description = serializers.CharField(max_length=4000)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    files = serializers.ListField(child=serializers.FileField(), required=False)


class MyTrustViewSet(ContextBindingMixin, GenericViewSet):
    """A person's privacy centre, appeals and insurance claims."""

    permission_classes = [IsEndUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = DataRequest.objects.none()

    @extend_schema(methods=["GET"], responses={200: OpenApiTypes.OBJECT})
    @extend_schema(
        methods=["POST"], request=ConsentSerializer, responses={200: OpenApiTypes.OBJECT}
    )
    @action(detail=False, methods=["get", "post"])
    def privacy(self, request):
        if request.method == "POST":
            data = ConsentSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            privacy.set_consent(request.user, **data.validated_data, ip=client_ip(request))
        return Response(
            {
                "consents": privacy.consents(request.user),
                "purposes": dict(ConsentPurpose.choices),
                "notice_version": privacy.NOTICE_VERSION,
                "retention": [
                    {"data": d, "kept_for": k, "why": w} for d, k, w in privacy.RETENTION
                ],
                "requests": DataRequestSerializer(
                    DataRequest.objects.filter(user=request.user), many=True
                ).data,
                "erasure_blockers": privacy.erasure_blockers(request.user),
                "response_days": privacy.queue_summary()["response_days"],
            }
        )

    @extend_schema(request=SubmitRequestSerializer, responses={201: DataRequestSerializer})
    @action(detail=False, methods=["post"], url_path="privacy/requests")
    def privacy_request(self, request):
        data = SubmitRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        made = privacy.submit(
            request.user,
            data.validated_data["kind"],
            details=data.validated_data.get("details", ""),
        )
        return Response(DataRequestSerializer(made).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=DataRequestSerializer)
    @action(detail=False, methods=["post"], url_path=r"privacy/requests/(?P<pk>\d+)/cancel")
    def privacy_cancel(self, request, pk=None):
        made = privacy.cancel(
            get_object_or_404(DataRequest, pk=pk, user=request.user), user=request.user
        )
        return Response(DataRequestSerializer(made).data)

    @extend_schema(responses={(200, "application/zip"): OpenApiTypes.BINARY})
    @action(detail=False, methods=["get"], url_path=r"privacy/requests/(?P<pk>\d+)/download")
    def privacy_download(self, request, pk=None):
        made = get_object_or_404(DataRequest, pk=pk, user=request.user, kind=RequestKind.EXPORT)
        if not DataRequestSerializer(made).data["download"]:
            raise ActionNotPermitted("This download has expired. Ask for a new copy.")
        return FileResponse(
            made.export_file.open("rb"), as_attachment=True, filename=f"{made.number}.zip"
        )

    @extend_schema(methods=["GET"], responses=AppealSerializer(many=True))
    @extend_schema(
        methods=["POST"], request=SubmitAppealSerializer, responses={201: AppealSerializer}
    )
    @action(detail=False, methods=["get", "post"], url_path="appeals")
    def my_appeals(self, request):
        if request.method == "POST":
            data = SubmitAppealSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            made = appeals.submit(request.user, **data.validated_data)
            return Response(AppealSerializer(made).data, status=status.HTTP_201_CREATED)
        return Response(AppealSerializer(Appeal.objects.filter(user=request.user), many=True).data)

    @extend_schema(methods=["GET"], responses=ClaimSerializer(many=True))
    @extend_schema(methods=["POST"], request=FileClaimSerializer, responses={201: ClaimSerializer})
    @action(detail=False, methods=["get", "post"], url_path="claims")
    def my_claims(self, request):
        if request.method == "POST":
            data = FileClaimSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            fields = dict(data.validated_data)
            trip = get_object_or_404(Trip, pk=fields.pop("trip"))
            made = claims.file_claim(
                trip, user=request.user, files=fields.pop("files", []), **fields
            )
            return Response(ClaimSerializer(made).data, status=status.HTTP_201_CREATED)
        rows = InsuranceClaim.objects.filter(claimant=request.user).prefetch_related("documents")
        return Response(ClaimSerializer(rows, many=True).data)

    @extend_schema(request=None, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"tickets/(?P<pk>\d+)/rate")
    def rate_ticket(self, request, pk=None):
        ticket = get_object_or_404(SupportTicket, pk=pk, raised_by=request.user)
        rating = support_quality.rate(
            ticket,
            user=request.user,
            score=int(request.data.get("score", 0)),
            comment=request.data.get("comment", ""),
        )
        return Response({"score": rating.score}, status=status.HTTP_201_CREATED)


# --- Help centre -----------------------------------------------------------------------------


class HelpArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpArticle
        fields = [
            "id",
            "slug",
            "title",
            "body",
            "category",
            "audience",
            "keywords",
            "views",
            "is_published",
        ]


class HelpViewSet(ContextBindingMixin, GenericViewSet):
    """Help articles for the signed-in person's app (riders or drivers)."""

    permission_classes = [IsAuthenticated]
    queryset = HelpArticle.objects.none()
    lookup_field = "slug"

    def _audience(self, request) -> str:
        if request.user.is_driver:
            return Audience.DRIVER
        if request.user.is_rider:
            return Audience.RIDER
        return Audience.STAFF  # staff read the internal handbook

    def _visible(self, request):
        """Riders and drivers never see internal handbook pages."""
        audience = self._audience(request)
        if audience == Audience.STAFF:
            return HelpArticle.objects.filter(is_published=True)
        return HelpArticle.objects.filter(is_published=True, audience__in=[audience, Audience.ALL])

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=False),
            OpenApiParameter("category", str, required=False),
        ],
        responses=HelpArticleSerializer(many=True),
    )
    def list(self, request):
        rows = support_quality.search(
            request.query_params.get("q", ""),
            audience=self._audience(request),
            category=request.query_params.get("category", ""),
        )
        return Response(HelpArticleSerializer(rows, many=True).data)

    @extend_schema(responses=HelpArticleSerializer)
    def retrieve(self, request, slug=None):
        article = get_object_or_404(self._visible(request), slug=slug)
        support_quality.view(article)
        return Response(HelpArticleSerializer(article).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def vote(self, request, slug=None):
        article = get_object_or_404(self._visible(request), slug=slug)
        support_quality.vote(article, user=request.user, helpful=bool(request.data.get("helpful")))
        return Response({"ok": True})


# --- Ops -------------------------------------------------------------------------------------


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=2000)
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class OutcomeSerializer(serializers.Serializer):
    outcome = serializers.CharField(max_length=2000)
    reject = serializers.BooleanField(default=False)


class MacroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Macro
        fields = ["id", "title", "body", "category", "uses", "is_active"]
        read_only_fields = ["uses"]


class OfferSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=300)


class TrustOpsViewSet(BaseViewSet):
    """Privacy queue, appeals, claims desk, CSAT, saved replies, help articles, offers."""

    capabilities = {
        "*": Cap.PRIVACY_MANAGE,
        "csat": Cap.SUPPORT_VIEW,
        "macros": Cap.SUPPORT_VIEW,
        "use_macro": Cap.SUPPORT_MANAGE,
        "articles": Cap.SUPPORT_MANAGE,
        "offer": Cap.PROMOS_MANAGE,
    }
    queryset = DataRequest.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def overview(self, request):
        from .models import AppealStatus, ClaimStatus

        return Response(
            {
                "privacy": privacy.queue_summary(),
                "requests": DataRequestSerializer(DataRequest.objects.all()[:50], many=True).data,
                "appeals": AppealSerializer(
                    Appeal.objects.select_related("user", "original_decided_by", "reviewed_by")[
                        :50
                    ],
                    many=True,
                ).data,
                "open_appeals": Appeal.objects.filter(status=AppealStatus.OPEN).count(),
                "claims": ClaimSerializer(
                    InsuranceClaim.objects.select_related("trip", "claimant").prefetch_related(
                        "documents"
                    )[:50],
                    many=True,
                ).data,
                "open_claims": InsuranceClaim.objects.filter(
                    status__in=[ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW]
                ).count(),
                "marketing_audience": privacy.marketing_audience().count(),
            }
        )

    @extend_schema(request=OutcomeSerializer, responses=DataRequestSerializer)
    @action(detail=False, methods=["post"], url_path=r"requests/(?P<pk>\d+)/resolve")
    def resolve_request(self, request, pk=None):
        data = OutcomeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        made = privacy.resolve(
            get_object_or_404(DataRequest, pk=pk), actor=request.user, **data.validated_data
        )
        return Response(DataRequestSerializer(made).data)

    @extend_schema(request=DecisionSerializer, responses=AppealSerializer)
    @action(detail=False, methods=["post"], url_path=r"appeals/(?P<pk>\d+)/decide")
    def decide_appeal(self, request, pk=None):
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        made = appeals.decide(
            get_object_or_404(Appeal, pk=pk),
            reviewer=request.user,
            uphold=data.validated_data["approve"],
            note=data.validated_data["note"],
        )
        return Response(AppealSerializer(made).data)

    @extend_schema(request=None, responses=ClaimSerializer)
    @action(detail=False, methods=["post"], url_path=r"claims/(?P<pk>\d+)/review")
    def review_claim(self, request, pk=None):
        made = claims.start_review(get_object_or_404(InsuranceClaim, pk=pk), reviewer=request.user)
        return Response(ClaimSerializer(made).data)

    @extend_schema(request=DecisionSerializer, responses=ClaimSerializer)
    @action(detail=False, methods=["post"], url_path=r"claims/(?P<pk>\d+)/decide")
    def decide_claim(self, request, pk=None):
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        made = claims.decide(
            get_object_or_404(InsuranceClaim, pk=pk), reviewer=request.user, **data.validated_data
        )
        return Response(ClaimSerializer(made).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def csat(self, request):
        return Response(
            {"csat": support_quality.csat_summary(), "help": support_quality.help_stats()}
        )

    @extend_schema(
        methods=["GET"],
        parameters=[OpenApiParameter("category", str, required=False)],
        responses=MacroSerializer(many=True),
    )
    @extend_schema(methods=["POST"], request=MacroSerializer, responses={201: MacroSerializer})
    @action(detail=False, methods=["get", "post"])
    def macros(self, request):
        if request.method == "POST":
            if not request.user.has_capability(Cap.SUPPORT_MANAGE):
                raise ActionNotPermitted("Your role can't add saved replies.")
            data = MacroSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            return Response(
                MacroSerializer(data.save(created_by=request.user)).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(
            MacroSerializer(
                support_quality.macros_for(request.query_params.get("category", "")), many=True
            ).data
        )

    @extend_schema(request=None, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"macros/(?P<pk>\d+)/use/(?P<ticket_id>\d+)")
    def use_macro(self, request, pk=None, ticket_id=None):
        message = support_quality.use_macro(
            get_object_or_404(Macro, pk=pk),
            get_object_or_404(SupportTicket, pk=ticket_id),
            agent=request.user,
        )
        return Response({"message_id": message.pk}, status=status.HTTP_201_CREATED)

    @extend_schema(methods=["GET"], responses=HelpArticleSerializer(many=True))
    @extend_schema(
        methods=["POST"], request=HelpArticleSerializer, responses={201: HelpArticleSerializer}
    )
    @action(detail=False, methods=["get", "post"])
    def articles(self, request):
        if request.method == "POST":
            data = HelpArticleSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            return Response(HelpArticleSerializer(data.save()).data, status=status.HTTP_201_CREATED)
        return Response(HelpArticleSerializer(HelpArticle.objects.all(), many=True).data)

    @extend_schema(request=OfferSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def offer(self, request):
        data = OfferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response({"sent": privacy.announce_offer(actor=request.user, **data.validated_data)})


# --- NPS ------------------------------------------------------------------------------------------


class NpsAnswerSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=0, max_value=10)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class NpsViewSet(BaseViewSet):
    """Riders and drivers answer the survey; ops read the report."""

    rider_actions = ("prompt", "answer", "snooze")
    driver_actions = ("prompt", "answer", "snooze")
    capabilities = {"report": Cap.REPORTS_VIEW}
    queryset = HelpArticle.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def prompt(self, request):
        from . import nps

        return Response({"ask": nps.should_ask(request.user)})

    @extend_schema(request=NpsAnswerSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def answer(self, request):
        from . import nps

        data = NpsAnswerSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        nps.answer(request.user, **data.validated_data)
        return Response({"thanks": True}, status=201)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def snooze(self, request):
        from . import nps

        nps.snooze(request.user)
        return Response({"ok": True})

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def report(self, request):
        from . import nps

        return Response(nps.report())
