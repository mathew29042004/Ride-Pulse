from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, Throttled
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.core.api import BaseViewSet, ContextBindingMixin
from apps.geo.models import City

from . import otp
from .models import Role, StaffProfile
from .roles import Cap

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "language",
            "role",
            "role_label",
            "capabilities",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "capabilities", "date_joined"]

    def validate_email(self, value: str) -> str:
        """Riders who signed up by phone add an address here (for invoices)."""
        taken = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Another account already uses this email.")
        return value.lower()

    def get_capabilities(self, user) -> list[str]:
        return sorted(user.capabilities)


class AccountLocked(Throttled):
    default_detail = "Too many wrong passwords."
    default_code = "account_locked"

    def __init__(self, detail: str):
        super().__init__(wait=None, detail=detail)


class RidePulseTokenSerializer(TokenObtainPairSerializer):
    """Adds the role and name to the JWT and returns the user next to the tokens."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["name"] = user.get_full_name()
        return token

    def validate(self, attrs):
        from apps.reliability import security

        email = str(attrs.get(self.username_field, ""))
        request = self.context.get("request")
        until = security.locked_until(email)
        if until:
            minutes = max(1, round((until - timezone.now()).total_seconds() / 60))
            raise AccountLocked(
                f"Too many wrong passwords. Try again in {minutes} min, "
                "or sign in with a phone code."
            )
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            if security.login_failed(email, request=request):
                raise AccountLocked(
                    "Too many wrong passwords. Your account is locked for 15 minutes."
                ) from None
            raise
        from . import two_factor

        if self.user.is_staff_member and two_factor.is_enabled(self.user):
            # Password was right; now the second step. No tokens until the code checks out.
            return {"two_factor_required": True, "challenge": two_factor.challenge_for(self.user)}
        data["user"] = UserSerializer(self.user).data
        return data


class TokenView(TokenObtainPairView):
    """Exchange email and password for an access token (30 min) and refresh token (7 days).
    Five wrong passwords in 15 minutes lock the account for 15 minutes."""

    serializer_class = RidePulseTokenSerializer
    throttle_scope = "login"


def tokens_for(user) -> dict:
    refresh = RidePulseTokenSerializer.get_token(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutView(ContextBindingMixin, APIView):
    """Blacklist a refresh token so it can't be used again."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=LogoutSerializer, responses={205: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": [str(exc)]}) from exc
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(ContextBindingMixin, generics.RetrieveUpdateAPIView):
    """The signed-in user's account."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


class _RegisterBase(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.RegexField(r"^\+?\d{10,13}$", required=False, allow_blank=True)

    def validate_password(self, value):
        validate_password(value)
        return value


class RiderRegistrationSerializer(_RegisterBase):
    referral_code = serializers.CharField(required=False, allow_blank=True, max_length=12)


class DriverRegistrationSerializer(_RegisterBase):
    city = serializers.SlugRelatedField(
        slug_field="slug", queryset=City.objects.filter(is_active=True)
    )
    license_number = serializers.CharField(max_length=20)
    license_expiry = serializers.DateField()
    gender = serializers.ChoiceField(
        choices=["FEMALE", "MALE", "UNDISCLOSED"], required=False, default="UNDISCLOSED"
    )


class RegistrationResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


class RegisterRiderView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "registration"

    @extend_schema(
        request=RiderRegistrationSerializer, responses={201: RegistrationResponseSerializer}
    )
    def post(self, request):
        from apps.riders.services import register_rider

        serializer = RiderRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = register_rider(**serializer.validated_data)
        return Response(
            {"user": UserSerializer(profile.user).data, **tokens_for(profile.user)},
            status=status.HTTP_201_CREATED,
        )


class RegisterDriverView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "registration"

    @extend_schema(
        request=DriverRegistrationSerializer, responses={201: RegistrationResponseSerializer}
    )
    def post(self, request):
        from apps.drivers.services import register_driver

        serializer = DriverRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver = register_driver(**serializer.validated_data)
        return Response(
            {"user": UserSerializer(driver.user).data, **tokens_for(driver.user)},
            status=status.HTTP_201_CREATED,
        )


class StaffUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "is_active",
            "password",
            "last_login",
        ]
        read_only_fields = ["id", "last_login"]

    def validate_role(self, value):
        if value in (Role.RIDER, Role.DRIVER):
            raise serializers.ValidationError("Riders and drivers sign up through the apps.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user


class StaffUserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    BaseViewSet,
):
    """Back-office accounts (admins, operations managers, support agents)."""

    queryset = User.objects.exclude(role__in=[Role.RIDER, Role.DRIVER])
    serializer_class = StaffUserSerializer
    capabilities = {"*": Cap.USERS_MANAGE}
    filterset_fields = ["role", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    http_method_names = ["get", "post", "patch"]


# --- Phone (OTP) login -------------------------------------------------------------------


class OtpRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)


class OtpVerifySerializer(OtpRequestSerializer):
    code = serializers.CharField(max_length=6, min_length=6)


class OtpSignupSerializer(serializers.Serializer):
    signup_token = serializers.CharField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class OtpRequestView(APIView):
    """Text a 6-digit login code to an Indian mobile number."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "otp"

    @extend_schema(
        request=OtpRequestSerializer, responses={200: OpenApiTypes.OBJECT}, tags=["auth"]
    )
    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = otp.request_code(
            serializer.validated_data["phone"], ip=request.META.get("REMOTE_ADDR")
        )
        body = {
            "phone": challenge.phone,
            "expires_in": challenge.expires_in,
            "resend_in": challenge.resend_in,
        }
        if challenge.debug_code:
            body["debug_code"] = challenge.debug_code  # development only: no SMS is sent
        return Response(body)


class OtpVerifyView(APIView):
    """Check the code. Known numbers get tokens; new numbers get a token to finish signing up."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "otp"

    @extend_schema(request=OtpVerifySerializer, responses={200: OpenApiTypes.OBJECT}, tags=["auth"])
    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = otp.verify_code(**serializer.validated_data)
        if result.user is None:
            return Response({"new_user": True, "signup_token": result.signup_token})
        from . import two_factor

        if result.user.is_staff_member and two_factor.is_enabled(result.user):
            return Response(
                {"two_factor_required": True, "challenge": two_factor.challenge_for(result.user)}
            )
        return Response(
            {"new_user": False, "user": UserSerializer(result.user).data, **tokens_for(result.user)}
        )


class OtpSignupView(APIView):
    """Finish signing up a verified new number as a rider (just a name needed)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "registration"

    @extend_schema(
        request=OtpSignupSerializer, responses={201: RegistrationResponseSerializer}, tags=["auth"]
    )
    def post(self, request):
        serializer = OtpSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = otp.complete_signup(**serializer.validated_data)
        return Response(
            {"user": UserSerializer(profile.user).data, **tokens_for(profile.user)},
            status=status.HTTP_201_CREATED,
        )


class StaffDirectorySerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.get_full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    role = serializers.CharField(source="user.role", read_only=True)
    role_label = serializers.CharField(source="user.get_role_display", read_only=True)
    department_label = serializers.CharField(source="get_department_display", read_only=True)
    city = serializers.CharField(source="city.name", default="", read_only=True)
    reports_to = serializers.CharField(
        source="reports_to.user.get_full_name", default="", read_only=True
    )
    drivers = serializers.IntegerField(source="driver_count", read_only=True, default=0)

    class Meta:
        model = StaffProfile
        fields = [
            "id",
            "employee_id",
            "name",
            "email",
            "role",
            "role_label",
            "title",
            "department",
            "department_label",
            "state",
            "city",
            "reports_to",
            "drivers",
            "joined_on",
        ]


class TeamViewSet(mixins.ListModelMixin, BaseViewSet):
    """The staff directory and org chart (managers and associate managers)."""

    serializer_class = StaffDirectorySerializer
    capabilities = {"list": Cap.TEAM_VIEW, "tree": Cap.TEAM_VIEW, "summary": Cap.TEAM_VIEW}
    filterset_fields = ["department", "state", "user__role"]
    search_fields = ["user__first_name", "user__last_name", "user__email", "employee_id", "title"]

    def get_queryset(self):
        from django.db.models import Count

        return (
            StaffProfile.objects.select_related("user", "city", "reports_to__user")
            .annotate(driver_count=Count("drivers"))
            .order_by("employee_id")
        )

    @extend_schema(
        parameters=[OpenApiParameter("state", str, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def tree(self, request):
        from . import org

        return Response(org.tree(state=request.query_params.get("state") or None))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        from . import org

        return Response(org.summary())


# --- Two-step sign-in (staff) -------------------------------------------------------------------


class TwoFactorCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=12)


class TwoFactorChallengeSerializer(TwoFactorCodeSerializer):
    challenge = serializers.CharField(max_length=300)


class TwoFactorVerifyView(APIView):
    """Second step of sign-in: the challenge from the password step plus a 6-digit code (or a
    recovery code) gives the tokens."""

    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(request=TwoFactorChallengeSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from apps.reliability import security

        from . import two_factor

        data = TwoFactorChallengeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = two_factor.user_from_challenge(data.validated_data["challenge"])
        if security.locked_until(user.email):
            raise AccountLocked("Too many wrong codes. Try again in a few minutes.")
        if not two_factor.verify(user, data.validated_data["code"]):
            if security.login_failed(user.email, request=request):
                raise AccountLocked("Too many wrong codes. Your account is locked for 15 minutes.")
            raise serializers.ValidationError({"code": ["That code didn't match."]})
        return Response({"user": UserSerializer(user).data, **tokens_for(user)})


class TwoFactorView(ContextBindingMixin, APIView):
    """The signed-in staff member's own two-step settings: GET status, POST to start set-up."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        from . import two_factor

        return Response(two_factor.status(request.user))

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from . import two_factor

        return Response(two_factor.begin(request.user))


class TwoFactorEnableView(ContextBindingMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TwoFactorCodeSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from . import two_factor

        data = TwoFactorCodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        codes = two_factor.enable(request.user, data.validated_data["code"])
        return Response({"recovery_codes": codes, **two_factor.status(request.user)})


class TwoFactorDisableView(ContextBindingMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TwoFactorCodeSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from . import two_factor

        data = TwoFactorCodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        two_factor.disable(request.user, data.validated_data["code"])
        return Response(two_factor.status(request.user))
