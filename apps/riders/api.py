from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.conf import referral_bonus
from apps.payments.services import wallet_balance

from . import services
from .models import RiderProfile, SavedPlace


class IsRider(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_rider)


class RiderSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    wallet_balance = serializers.SerializerMethodField()

    class Meta:
        model = RiderProfile
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "rating",
            "rating_count",
            "completed_trips",
            "referral_code",
            "default_payment_method",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_blocked",
            "blocked_reason",
            "wallet_balance",
            "created_at",
        ]
        read_only_fields = [
            "rating",
            "rating_count",
            "completed_trips",
            "referral_code",
            "is_blocked",
            "blocked_reason",
            "created_at",
        ]

    def get_wallet_balance(self, rider) -> str:
        return str(wallet_balance(rider.user))


class RidePassPurchaseSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["UPI", "CARD", "WALLET"])
    payer_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)


class RiderMeSerializer(RiderSerializer):
    """The rider's own profile: adds referral progress, ride preferences and favourites."""

    referrals = serializers.SerializerMethodField()
    favourites = serializers.SerializerMethodField()
    default_preferences = serializers.ListField(
        child=serializers.ChoiceField(choices=["QUIET", "AC", "LUGGAGE", "WOMAN_DRIVER"]),
        required=False,
    )

    class Meta(RiderSerializer.Meta):
        fields = [*RiderSerializer.Meta.fields, "referrals", "favourites", "default_preferences"]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_favourites(self, rider) -> list[dict]:
        return [
            {
                "id": d.pk,
                "name": d.name,
                "rating": str(d.rating),
                "vehicle": str(d.vehicles.filter(is_active=True).first() or ""),
            }
            for d in rider.favourite_drivers.select_related("user")
        ]

    @extend_schema_field(serializers.DictField())
    def get_referrals(self, rider) -> dict:
        """Friends who joined with this rider's code, and how many have earned the bonus."""
        joined = rider.referrals.count()
        rewarded = rider.referrals.filter(referral_rewarded_at__isnull=False).count()
        return {
            "joined": joined,
            "rewarded": rewarded,
            "bonus": str(referral_bonus()),
            "earned": str(referral_bonus() * rewarded),
        }


class BlockSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class RiderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Riders, for operations and support staff."""

    queryset = RiderProfile.objects.select_related("user")
    serializer_class = RiderSerializer
    capabilities = {
        "list": Cap.RIDERS_VIEW,
        "retrieve": Cap.RIDERS_VIEW,
        "block": Cap.RIDERS_MANAGE,
        "unblock": Cap.RIDERS_MANAGE,
    }
    filterset_fields = ["is_blocked"]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "user__phone",
        "referral_code",
    ]
    ordering_fields = ["created_at", "rating", "completed_trips"]

    @extend_schema(request=BlockSerializer, responses=RiderSerializer)
    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rider = services.set_blocked(
            self.get_object(),
            True,
            reason=serializer.validated_data.get("reason", ""),
            actor=request.user,
        )
        return Response(RiderSerializer(rider).data)

    @extend_schema(request=None, responses=RiderSerializer)
    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        rider = services.set_blocked(self.get_object(), False, actor=request.user)
        return Response(RiderSerializer(rider).data)


class RiderProfileViewSet(ContextBindingMixin, GenericViewSet):
    """The signed-in rider's own profile."""

    serializer_class = RiderMeSerializer
    permission_classes = [IsRider]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RiderProfile.objects.none()
        return RiderProfile.objects.filter(user=self.request.user)

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        profile = request.user.rider_profile
        if request.method == "PATCH":
            serializer = RiderMeSerializer(profile, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(RiderMeSerializer(profile).data)

    @extend_schema(request=RidePassPurchaseSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"], url_path="ride-pass")
    def ride_pass(self, request):
        """The Ride Pass offer and this rider's pass (GET), or buy / extend it (POST)."""
        from apps.core.conf import ride_pass_terms
        from apps.pricing import passes

        rider = request.user.rider_profile
        if request.method == "POST":
            serializer = RidePassPurchaseSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            passes.buy_pass(rider, **serializer.validated_data)
        current = passes.active_pass(rider)
        latest_end = rider.passes.values_list("ends_at", flat=True).first()
        terms = ride_pass_terms()
        return Response(
            {
                "plan": {k: str(v) for k, v in terms.items()},
                "active": current is not None,
                "ends_at": latest_end if current else None,
                "savings": str(passes.savings(rider)),
            }
        )

    @extend_schema(request=None, responses={204: None})
    @action(detail=False, methods=["delete"], url_path=r"favourites/(?P<driver_id>\d+)")
    def remove_favourite(self, request, driver_id=None):
        request.user.rider_profile.favourite_drivers.remove(int(driver_id))
        return Response(status=204)


class SavedPlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedPlace
        fields = ["id", "label", "name", "address", "lat", "lng"]


class SavedPlaceViewSet(ContextBindingMixin, ModelViewSet):
    """A rider's saved places (Home, Work and favourites)."""

    serializer_class = SavedPlaceSerializer
    permission_classes = [IsRider]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedPlace.objects.none()
        return SavedPlace.objects.filter(rider__user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(rider=self.request.user.rider_profile)
