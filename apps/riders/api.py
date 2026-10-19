from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.core.conf import referral_bonus
from apps.payments.services import wallet_balance

from . import services
from .models import (
    MemberStatus,
    PaymentProfile,
    ProfileMember,
    RiderProfile,
    SavedPlace,
    TeenLink,
    TeenStatus,
    TrustedContact,
)


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
            "night_safety",
            "ride_pin",
            "accessibility",
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

    def validate_accessibility(self, value: list[str]) -> list[str]:
        from apps.rides.models import ACCESSIBILITY_NEEDS

        unknown = set(value) - set(ACCESSIBILITY_NEEDS)
        if unknown:
            raise serializers.ValidationError(f"Unknown need: {', '.join(sorted(unknown))}")
        return sorted(set(value))

    def validate_ride_pin(self, value: str) -> str:
        if value and (len(value) != 4 or not value.isdigit()):
            raise serializers.ValidationError("Your Ride PIN must be 4 digits.")
        if value and len(set(value)) == 1:
            raise serializers.ValidationError("Pick a PIN that's harder to guess.")
        return value

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
        child=serializers.ChoiceField(
            choices=["QUIET", "AC", "LUGGAGE", "WOMAN_DRIVER", "ELECTRIC"]
        ),
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

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="fare-locks")
    def fare_locks(self, request):
        """This rider's Fare Locks (active first)."""
        from apps.rides.api import fare_lock_payload

        locks = request.user.rider_profile.fare_locks.select_related("ride_type")[:10]
        return Response([fare_lock_payload(lock) for lock in locks])

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"])
    def eco(self, request):
        """Eco score: CO2 saved and points (GET), or turn points into wallet money (POST)."""
        from apps.rides import eco

        rider = request.user.rider_profile
        if request.method == "POST":
            return Response(eco.redeem(rider))
        return Response(eco.summary(rider))

    @extend_schema(request=None, responses={204: None})
    @action(detail=False, methods=["delete"], url_path=r"favourites/(?P<driver_id>\d+)")
    def remove_favourite(self, request, driver_id=None):
        request.user.rider_profile.favourite_drivers.remove(int(driver_id))
        return Response(status=204)


class SavedPlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedPlace
        fields = ["id", "label", "name", "address", "lat", "lng"]


MAX_TRUSTED_CONTACTS = 3


class TrustedContactSerializer(serializers.ModelSerializer):
    share_mode_label = serializers.CharField(source="get_share_mode_display", read_only=True)
    # Accept "+91 98765 43210" and the like; stored as 10 digits.
    phone = serializers.CharField(max_length=20)

    class Meta:
        model = TrustedContact
        fields = ["id", "name", "phone", "share_mode", "share_mode_label", "created_at"]
        read_only_fields = ["created_at"]

    def validate_phone(self, value: str) -> str:
        from apps.core.validators import normalize_indian_mobile

        try:
            return normalize_indian_mobile(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class TrustedContactViewSet(ContextBindingMixin, ModelViewSet):
    """Up to three people who get the live trip link (and Ride Check alerts)."""

    serializer_class = TrustedContactSerializer
    permission_classes = [IsRider]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TrustedContact.objects.none()
        return TrustedContact.objects.filter(rider__user=self.request.user)

    def perform_create(self, serializer):
        from django.db import IntegrityError, transaction

        from apps.core.exceptions import BusinessRuleViolation, ConflictError

        rider = self.request.user.rider_profile
        if rider.contacts.count() >= MAX_TRUSTED_CONTACTS:
            raise BusinessRuleViolation(f"You can add up to {MAX_TRUSTED_CONTACTS} contacts.")
        try:
            with transaction.atomic():
                serializer.save(rider=rider)
        except IntegrityError as exc:
            raise ConflictError("That number is already one of your contacts.") from exc


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


class ProfileMemberSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="rider.name", read_only=True)
    phone = serializers.CharField(source="rider.user.phone", read_only=True)

    class Meta:
        model = ProfileMember
        fields = ["id", "name", "phone", "status", "monthly_limit", "joined_at"]


class PaymentProfileSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    owner_name = serializers.CharField(source="owner.name", read_only=True)
    role = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    spent_this_month = serializers.SerializerMethodField()
    my_limit = serializers.SerializerMethodField()
    invitation_id = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()
    my_cost_center = serializers.SerializerMethodField()

    class Meta:
        model = PaymentProfile
        fields = [
            "id",
            "kind",
            "kind_label",
            "name",
            "gstin",
            "credit_limit",
            "owner_name",
            "role",
            "members",
            "spent_this_month",
            "my_limit",
            "invitation_id",
            "is_admin",
            "cost_centers",
            "my_cost_center",
        ]
        read_only_fields = ["credit_limit", "cost_centers"]

    def _rider(self):
        return self.context["request"].user.rider_profile

    def _membership(self, profile):
        return profile.members.filter(rider=self._rider()).first()

    def get_role(self, profile) -> str:
        if profile.owner_id == self._rider().pk:
            return "OWNER"
        member = self._membership(profile)
        return "INVITED" if member and member.status == MemberStatus.INVITED else "MEMBER"

    @extend_schema_field(ProfileMemberSerializer(many=True))
    def get_members(self, profile) -> list:
        if profile.owner_id != self._rider().pk:
            return []
        rows = profile.members.exclude(status=MemberStatus.REMOVED).select_related("rider__user")
        return ProfileMemberSerializer(rows, many=True).data

    def get_spent_this_month(self, profile) -> str:
        from django.utils import timezone

        from .profiles import spent_this_month

        return str(spent_this_month(profile, self._rider(), timezone.now()))

    def get_my_limit(self, profile) -> str | None:
        member = self._membership(profile)
        return str(member.monthly_limit) if member and member.monthly_limit is not None else None

    def get_is_admin(self, profile) -> bool:
        member = self._membership(profile)
        return bool(member and member.is_admin and member.status == MemberStatus.ACTIVE)

    def get_my_cost_center(self, profile) -> str:
        member = self._membership(profile)
        return member.default_cost_center if member else ""

    def get_invitation_id(self, profile) -> int | None:
        member = self._membership(profile)
        return member.pk if member and member.status == MemberStatus.INVITED else None


class InviteSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)


class RespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class MemberUpdateSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    monthly_limit = serializers.DecimalField(
        max_digits=9, decimal_places=2, required=False, allow_null=True
    )
    remove = serializers.BooleanField(required=False, default=False)


class PaymentProfileViewSet(ContextBindingMixin, ModelViewSet):
    """Family and business profiles: one payer for several riders."""

    serializer_class = PaymentProfileSerializer
    permission_classes = [IsRider]
    pagination_class = None
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        from django.db.models import Q

        if getattr(self, "swagger_fake_view", False):
            return PaymentProfile.objects.none()
        rider = self.request.user.rider_profile
        return (
            PaymentProfile.objects.filter(is_active=True)
            .filter(
                Q(owner=rider)
                | Q(
                    members__rider=rider,
                    members__status__in=[MemberStatus.ACTIVE, MemberStatus.INVITED],
                )
            )
            .select_related("owner__user")
            .distinct()
        )

    def perform_create(self, serializer):
        from . import profiles

        data = serializer.validated_data
        serializer.instance = profiles.create_profile(
            self.request.user.rider_profile,
            kind=data["kind"],
            name=data["name"],
            gstin=data.get("gstin", ""),
        )

    def perform_destroy(self, instance):
        from . import profiles

        profiles.deactivate(instance, user=self.request.user)

    def _respond(self, profile):
        return Response(self.get_serializer(profile).data)

    @extend_schema(request=InviteSerializer, responses=PaymentProfileSerializer)
    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        from . import profiles

        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self.get_object()
        profiles.invite(profile, user=request.user, phone=serializer.validated_data["phone"])
        return self._respond(profile)

    @extend_schema(request=RespondSerializer, responses=PaymentProfileSerializer)
    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        from . import profiles

        serializer = RespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self.get_object()
        member = get_object_or_404(ProfileMember, profile=profile, rider=request.user.rider_profile)
        profiles.respond(member, user=request.user, accept=serializer.validated_data["accept"])
        return self._respond(profile)

    @extend_schema(request=MemberUpdateSerializer, responses=PaymentProfileSerializer)
    @action(detail=True, methods=["post"])
    def member(self, request, pk=None):
        """Owner: set a member's monthly limit, or remove them."""
        from . import profiles

        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = self.get_object()
        member = get_object_or_404(ProfileMember, pk=data["member_id"], profile=profile)
        profiles.update_member(
            member,
            user=request.user,
            monthly_limit=data.get("monthly_limit"),
            remove=data.get("remove", False),
        )
        return self._respond(profile)

    @extend_schema(
        parameters=[
            OpenApiParameter("month", str, required=False, description="YYYY-MM"),
            OpenApiParameter("export", str, required=False, enum=["csv"]),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """Owner: every ride on the profile in a month (JSON, or CSV with ?export=csv)."""
        import csv

        from django.http import HttpResponse

        from . import profiles

        data = profiles.statement(
            self.get_object(), user=request.user, month=request.query_params.get("month")
        )
        if request.query_params.get("export") != "csv":
            return Response(data)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="ride-pulse-{data["month"]}-statement.csv"'
        )
        writer = csv.writer(response)
        columns = [
            "trip_number",
            "date",
            "rider",
            "ride_type",
            "from",
            "to",
            "purpose",
            "fare",
            "gst",
        ]
        writer.writerow(columns)
        for row in data["trips"]:
            writer.writerow([row[c] for c in columns])
        writer.writerow([])
        writer.writerow(["Total", "", "", "", "", "", "", data["total"], data["gst"]])
        return response


class TeenInviteSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    monthly_limit = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True, min_value=0
    )


class TeenAcceptSerializer(serializers.Serializer):
    birth_year = serializers.IntegerField(min_value=1990, max_value=2030)


class TeenCurfewSerializer(serializers.Serializer):
    start = serializers.IntegerField(min_value=0, max_value=23)
    end = serializers.IntegerField(min_value=0, max_value=23)


class TeenViewSet(ContextBindingMixin, GenericViewSet):
    """Teen accounts: a parent's linked teens, and a teen's pending invitation."""

    permission_classes = [IsRider]
    queryset = TeenLink.objects.none()

    def _state(self, rider):
        from . import teens

        invitation = (
            TeenLink.objects.filter(teen=rider, status__in=[TeenStatus.INVITED, TeenStatus.ACTIVE])
            .select_related("guardian__user")
            .first()
        )
        return {
            "teens": teens.guardian_view(rider),
            "my_guardian": {
                "id": invitation.pk,
                "name": invitation.guardian.user.get_full_name(),
                "status": invitation.status,
                "curfew": [invitation.curfew_start, invitation.curfew_end],
            }
            if invitation
            else None,
        }

    def _link(self, pk):
        from django.db.models import Q

        rider = self.request.user.rider_profile
        return get_object_or_404(TeenLink.objects.filter(Q(guardian=rider) | Q(teen=rider)), pk=pk)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        return Response(self._state(request.user.rider_profile))

    @extend_schema(request=TeenInviteSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from . import teens

        data = TeenInviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        teens.invite(request.user.rider_profile, **data.validated_data)
        return Response(self._state(request.user.rider_profile), status=status.HTTP_201_CREATED)

    @extend_schema(request=TeenAcceptSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        from . import teens

        data = TeenAcceptSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        teens.accept(self._link(pk), user=request.user, **data.validated_data)
        return Response(self._state(request.user.rider_profile))

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        from . import teens

        teens.decline_or_end(self._link(pk), user=request.user)
        return Response(self._state(request.user.rider_profile))

    @extend_schema(request=TeenCurfewSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def curfew(self, request, pk=None):
        from . import teens

        data = TeenCurfewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        teens.set_curfew(self._link(pk), user=request.user, **data.validated_data)
        return Response(self._state(request.user.rider_profile))


class CorporatePolicySerializer(serializers.Serializer):
    allowed_ride_types = serializers.ListField(
        child=serializers.CharField(max_length=10), required=False
    )
    allowed_from_hour = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=23
    )
    allowed_to_hour = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=23
    )
    max_fare_per_trip = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    cost_centers = serializers.ListField(child=serializers.CharField(max_length=40), required=False)


class CorporateEmployeeSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    is_admin = serializers.BooleanField(required=False)
    default_cost_center = serializers.CharField(required=False, allow_blank=True, max_length=40)


class CorporateWebhookSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    url = serializers.URLField(max_length=300)


class CommutePlanSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    office_name = serializers.CharField(max_length=80)
    office_lat = serializers.FloatField()
    office_lng = serializers.FloatField()
    ride_type = serializers.CharField(max_length=10)
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6))
    arrive_by = serializers.TimeField()
    leave_at = serializers.TimeField()


class CommuteEnrolSerializer(serializers.Serializer):
    plan = serializers.IntegerField()
    home_lat = serializers.FloatField()
    home_lng = serializers.FloatField()
    home_address = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    morning = serializers.BooleanField(default=True)
    evening = serializers.BooleanField(default=True)


class CommuteSkipSerializer(serializers.Serializer):
    enrolment = serializers.IntegerField()
    date = serializers.DateField()
    skip = serializers.BooleanField(default=True)


class CommuteViewSet(ContextBindingMixin, GenericViewSet):
    """Employees: office commute plans from their companies, enrolment and skipping days."""

    permission_classes = [IsRider]
    queryset = PaymentProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="rider_commute_list")
    def list(self, request):
        from . import commute
        from .models import MemberStatus

        rider = request.user.rider_profile
        mine = commute.CommuteEnrolment.objects.filter(rider=rider, is_active=True).select_related(
            "plan__profile", "plan__ride_type"
        )
        enrolled = {e.plan_id for e in mine}
        offered = (
            commute.CommutePlan.objects.filter(
                is_active=True,
                profile__members__rider=rider,
                profile__members__status=MemberStatus.ACTIVE,
            )
            .select_related("profile", "ride_type")
            .exclude(pk__in=enrolled)
        )
        return Response(
            {
                "enrolments": [commute.enrolment_row(e) for e in mine],
                "plans": [
                    {**commute.plan_row(p), "company": p.profile.name} for p in offered.distinct()
                ],
            }
        )

    @extend_schema(request=CommuteEnrolSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def enrol(self, request):
        from . import commute

        data = CommuteEnrolSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        plan = get_object_or_404(commute.CommutePlan, pk=v["plan"])
        e = commute.enrol(
            plan,
            rider=request.user.rider_profile,
            home=(v["home_lat"], v["home_lng"]),
            home_address=v["home_address"],
            morning=v["morning"],
            evening=v["evening"],
        )
        return Response(commute.enrolment_row(e))

    @extend_schema(request=CommuteSkipSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def skip(self, request):
        from . import commute

        data = CommuteSkipSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        e = get_object_or_404(
            commute.CommuteEnrolment, pk=v["enrolment"], rider=request.user.rider_profile
        )
        return Response(commute.enrolment_row(commute.skip(e, v["date"], skip=v["skip"])))

    @extend_schema(request=CommuteSkipSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def leave(self, request):
        from . import commute

        e = get_object_or_404(
            commute.CommuteEnrolment,
            pk=request.data.get("enrolment"),
            rider=request.user.rider_profile,
        )
        e.is_active = False
        e.save(update_fields=["is_active"])
        from apps.rides.models import ScheduledRide, ScheduledRideStatus

        ScheduledRide.objects.filter(commute=e, status=ScheduledRideStatus.SCHEDULED).update(
            status=ScheduledRideStatus.CANCELLED
        )
        return Response({"left": True})


class CorporateViewSet(ContextBindingMixin, GenericViewSet):
    """The corporate portal: dashboard, travel policy, employees, invoice and webhooks."""

    permission_classes = [IsRider]
    queryset = PaymentProfile.objects.none()

    def _profile(self, pk):
        from . import corporate

        profile = get_object_or_404(PaymentProfile, pk=pk, kind="BUSINESS", is_active=True)
        corporate.require_manager(profile, self.request.user.rider_profile)
        return profile

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def retrieve(self, request, pk=None):
        from . import corporate

        return Response(corporate.dashboard(self._profile(pk)))

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="business_commute")
    @action(detail=True, methods=["get"])
    def commute(self, request, pk=None):
        """The company's commute plans with this month's rides and cost, and who's enrolled."""
        from . import commute

        profile = self._profile(pk)
        plans = profile.commute_plans.select_related("ride_type")
        return Response(
            {
                "plans": [
                    {
                        **commute.plan_row(p),
                        "employees": [
                            {
                                "name": e.rider.user.get_full_name(),
                                "home_address": e.home_address,
                                "morning": e.morning,
                                "evening": e.evening,
                                "skipping": [str(d) for d in e.skip_dates[:5]],
                            }
                            for e in p.enrolments.filter(is_active=True).select_related(
                                "rider__user"
                            )
                        ],
                    }
                    for p in plans
                ]
            }
        )

    @extend_schema(request=CommutePlanSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="commute/plan")
    def commute_plan(self, request, pk=None):
        from apps.pricing.models import RideType

        from . import commute

        data = CommutePlanSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        ride_type = get_object_or_404(RideType, code=v["ride_type"], is_active=True)
        plan = commute.create_plan(
            self._profile(pk),
            rider=request.user.rider_profile,
            name=v["name"],
            office_name=v["office_name"],
            office=(v["office_lat"], v["office_lng"]),
            ride_type=ride_type,
            weekdays=v["weekdays"],
            arrive_by=v["arrive_by"],
            leave_at=v["leave_at"],
        )
        return Response(commute.plan_row(plan), status=201)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path=r"commute/(?P<plan_id>\d+)/stop")
    def commute_stop(self, request, pk=None, plan_id=None):
        from apps.rides.models import ScheduledRide, ScheduledRideStatus

        from . import commute

        plan = get_object_or_404(commute.CommutePlan, pk=plan_id, profile=self._profile(pk))
        plan.is_active = False
        plan.save(update_fields=["is_active"])
        ScheduledRide.objects.filter(
            commute__plan=plan, status=ScheduledRideStatus.SCHEDULED
        ).update(status=ScheduledRideStatus.CANCELLED)
        return Response(commute.plan_row(plan))

    @extend_schema(
        parameters=[
            OpenApiParameter("month", str, required=False),
            OpenApiParameter("export", str, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
        operation_id="business_co2",
    )
    @action(detail=True, methods=["get"])
    def co2(self, request, pk=None):
        """Monthly CO₂ report for the company's sustainability reporting (CSV with ?export=csv)."""
        from django.http import HttpResponse

        from . import esg

        profile = self._profile(pk)
        month = request.query_params.get("month")
        if request.query_params.get("export") == "csv":
            body, name = esg.csv_export(profile, month=month)
            response = HttpResponse(body, content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{name}"'
            return response
        return Response(esg.report(profile, month=month))

    @extend_schema(request=CorporatePolicySerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def policy(self, request, pk=None):
        from . import corporate

        data = CorporatePolicySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile = corporate.update_policy(
            self._profile(pk), rider=request.user.rider_profile, **data.validated_data
        )
        return Response(corporate.dashboard(profile))

    @extend_schema(request=CorporateEmployeeSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def employee(self, request, pk=None):
        from . import corporate

        data = CorporateEmployeeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile = self._profile(pk)
        corporate.update_employee(profile, rider=request.user.rider_profile, **data.validated_data)
        return Response(corporate.dashboard(profile))

    @extend_schema(request=CorporateWebhookSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def webhook(self, request, pk=None):
        from . import corporate

        data = CorporateWebhookSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        endpoint = corporate.add_webhook(
            self._profile(pk), rider=request.user.rider_profile, **data.validated_data
        )
        return Response(
            {"id": endpoint.pk, "secret": endpoint.secret}, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        parameters=[OpenApiParameter("month", str, required=False)],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"])
    def invoice(self, request, pk=None):
        from django.http import HttpResponse

        from . import corporate

        pdf, number = corporate.invoice_pdf(
            self._profile(pk), month=request.query_params.get("month")
        )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{number}.pdf"'
        return response
