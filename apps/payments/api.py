import contextlib
import json

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, CapabilityPermission, ContextBindingMixin
from apps.core.exceptions import ActionNotPermitted, BusinessRuleViolation

from . import razorpay, services
from .models import ONLINE_METHODS, LedgerEntry, Payment, PaymentMethod, Payout

IDEMPOTENCY_HEADER = OpenApiParameter(
    "Idempotency-Key",
    str,
    OpenApiParameter.HEADER,
    description="Retries with the same key never charge twice",
)


class StatementEntrySerializer(serializers.ModelSerializer):
    reference = serializers.CharField(source="transaction.reference")
    kind = serializers.CharField(source="transaction.kind")
    kind_label = serializers.CharField(source="transaction.get_kind_display")
    description = serializers.CharField(source="transaction.description")
    trip_id = serializers.IntegerField(source="transaction.trip_id", allow_null=True)
    created_at = serializers.DateTimeField(source="transaction.created_at")

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "reference",
            "kind",
            "kind_label",
            "description",
            "trip_id",
            "amount",
            "created_at",
        ]


class WalletSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    statement = StatementEntrySerializer(many=True)


class ChargeSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    method = serializers.ChoiceField(
        choices=[m for m in PaymentMethod.choices if m[0] in ONLINE_METHODS]
    )
    payer_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)


class PaymentSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "reference",
            "user",
            "trip",
            "purpose",
            "method",
            "amount",
            "status",
            "gateway_reference",
            "failure_reason",
            "created_at",
        ]


class RazorpayOrderRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class RazorpayConfirmSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=40)
    razorpay_payment_id = serializers.CharField(max_length=40)
    razorpay_signature = serializers.CharField(max_length=128)


class WalletViewSet(mixins.ListModelMixin, BaseViewSet):
    """The signed-in rider's or driver's wallet: balance, statement, top-up and dues."""

    permission_classes = [IsAuthenticated]
    serializer_class = WalletSerializer
    pagination_class = None

    def get_queryset(self):
        return LedgerEntry.objects.none()

    def _check(self, request):
        if not request.user.is_end_user:
            raise ActionNotPermitted("Wallets belong to riders and drivers.")

    @extend_schema(responses=WalletSerializer)
    def list(self, request):
        self._check(request)
        services.ensure_wallet(request.user)
        return Response(
            WalletSerializer(
                {
                    "balance": services.wallet_balance(request.user),
                    "statement": services.wallet_statement(request.user),
                }
            ).data
        )

    @extend_schema(
        request=ChargeSerializer,
        responses={201: PaymentSerializer},
        parameters=[IDEMPOTENCY_HEADER],
    )
    @action(detail=False, methods=["post"], url_path="top-up")
    def top_up(self, request):
        self._check(request)
        serializer = ChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "amount" not in serializer.validated_data:
            raise serializers.ValidationError({"amount": ["This field is required."]})
        payment = services.top_up(
            request.user,
            serializer.validated_data["amount"],
            method=serializer.validated_data["method"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            payer_reference=serializer.validated_data.get("payer_reference", ""),
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RazorpayOrderRequestSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="razorpay-order")
    def razorpay_order(self, request):
        """Start a Razorpay Checkout top-up: returns what the browser needs to open Checkout."""
        self._check(request)
        serializer = RazorpayOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.start_razorpay_top_up(request.user, serializer.validated_data["amount"])
        user = request.user
        return Response(
            {
                "key_id": razorpay.key_id(),
                "order_id": payment.gateway_order_id,
                "amount": int(payment.amount * 100),
                "currency": "INR",
                "reference": payment.reference,
                "prefill": {
                    "name": user.get_full_name(),
                    "email": user.email,
                    "contact": user.phone,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=RazorpayConfirmSerializer, responses=PaymentSerializer)
    @action(detail=False, methods=["post"], url_path="razorpay-confirm")
    def razorpay_confirm(self, request):
        """Checkout succeeded in the browser: verify Razorpay's signature, then credit."""
        self._check(request)
        serializer = RazorpayConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = services.complete_razorpay_top_up(
            order_id=data["razorpay_order_id"],
            payment_id=data["razorpay_payment_id"],
            signature=data["razorpay_signature"],
            user=request.user,
        )
        return Response(PaymentSerializer(payment).data)

    @extend_schema(
        request=ChargeSerializer,
        responses={201: PaymentSerializer},
        parameters=[IDEMPOTENCY_HEADER],
    )
    @action(detail=False, methods=["post"], url_path="pay-dues")
    def pay_dues(self, request):
        self._check(request)
        serializer = ChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.pay_dues(
            request.user,
            method=serializer.validated_data["method"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            payer_reference=serializer.validated_data.get("payer_reference", ""),
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    queryset = Payment.objects.select_related("user")
    serializer_class = PaymentSerializer
    capabilities = {"*": Cap.PAYMENTS_VIEW}
    filterset_fields = ["status", "method", "purpose", "trip"]
    search_fields = ["reference", "gateway_reference", "user__email"]


class PayoutSerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="payee_name", read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "payout_number",
            "driver",
            "driver_name",
            "amount",
            "period_start",
            "period_end",
            "status",
            "bank_reference",
            "failure_reason",
            "paid_at",
            "created_at",
        ]


class PayoutActionSerializer(serializers.Serializer):
    bank_reference = serializers.CharField(required=False, max_length=40)
    reason = serializers.CharField(required=False, max_length=160)


class PayoutViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Weekly driver payouts. Drivers see their own; finance staff run and settle them."""

    queryset = Payout.objects.select_related("driver__user", "fleet_owner")
    serializer_class = PayoutSerializer
    filterset_fields = ["status", "driver"]
    driver_lookup = "driver"
    driver_actions = ("list", "retrieve")
    capabilities = {
        "list": Cap.PAYMENTS_VIEW,
        "retrieve": Cap.PAYMENTS_VIEW,
        "generate": Cap.PAYOUTS_MANAGE,
        "mark_paid": Cap.PAYOUTS_MANAGE,
        "mark_failed": Cap.PAYOUTS_MANAGE,
    }

    @extend_schema(request=None, responses=PayoutSerializer(many=True))
    @action(detail=False, methods=["post"])
    def generate(self, request):
        return Response(PayoutSerializer(services.create_weekly_payouts(), many=True).data)

    @extend_schema(request=PayoutActionSerializer, responses=PayoutSerializer)
    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        reference = request.data.get("bank_reference") or "UTR-MANUAL"
        return Response(
            PayoutSerializer(
                services.mark_payout_paid(self.get_object(), bank_reference=reference)
            ).data
        )

    @extend_schema(request=PayoutActionSerializer, responses=PayoutSerializer)
    @action(detail=True, methods=["post"], url_path="mark-failed")
    def mark_failed(self, request, pk=None):
        reason = request.data.get("reason") or "Bank rejected the transfer."
        payout = services.mark_payout_failed(self.get_object(), reason=reason, actor=request.user)
        return Response(PayoutSerializer(payout).data)


class LedgerView(ContextBindingMixin, APIView):
    """Platform account balances and a live integrity check of the double-entry ledger."""

    permission_classes = [CapabilityPermission]
    capabilities = {"get": Cap.PAYMENTS_VIEW}

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=["payments"])
    def get(self, request):
        return Response(
            {"accounts": services.account_balances(), "integrity": services.verify_ledger()}
        )


class RazorpayWebhookView(APIView):
    """Razorpay calls this when a payment is captured: credits the wallet even if the rider
    closed the app before Checkout reported back. Authenticated by the webhook signature."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["payments"]
    )
    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not razorpay.webhook_signature_valid(request.body, signature):
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        event = json.loads(request.body)
        if event.get("event") in ("payment.captured", "order.paid"):
            entity = event["payload"]["payment"]["entity"]
            # Unknown orders aren't ours (e.g. another integration on the same account).
            with contextlib.suppress(BusinessRuleViolation):
                services.complete_razorpay_top_up(
                    order_id=entity["order_id"], payment_id=entity["id"], verified=True
                )
        return Response({"ok": True})
