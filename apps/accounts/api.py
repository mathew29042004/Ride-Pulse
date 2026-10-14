from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, serializers, status
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
from .models import Role
from .roles import Cap

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
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


class RidePulseTokenSerializer(TokenObtainPairSerializer):
    """Adds the role and name to the JWT and returns the user next to the tokens."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["name"] = user.get_full_name()
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class TokenView(TokenObtainPairView):
    """Exchange email and password for an access token (30 min) and refresh token (7 days)."""

    serializer_class = RidePulseTokenSerializer


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
