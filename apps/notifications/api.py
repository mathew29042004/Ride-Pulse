from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.core.api import ContextBindingMixin

from . import services
from .models import Notification, PushSubscription


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "level", "link", "is_read", "created_at"]
        read_only_fields = ["title", "body", "level", "link", "created_at"]


class NotificationViewSet(
    ContextBindingMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    """The signed-in user's own notifications. Only ``is_read`` can be changed."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_read", "level"]
    http_method_names = ["get", "patch", "post"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(user=self.request.user)

    @extend_schema(
        request=None,
        responses=inline_serializer("MarkAllRead", {"updated": serializers.IntegerField()}),
    )
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        return Response({"updated": services.mark_all_read(request.user)})

    @extend_schema(
        responses=inline_serializer("UnreadCount", {"unread": serializers.IntegerField()})
    )
    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get", "post"])
    def preferences(self, request):
        """Quiet hours and the daily digest."""
        from apps.core.exceptions import BusinessRuleViolation

        from .models import NotificationPreference

        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        if request.method == "POST":
            data = request.data
            hours = [data.get("quiet_from"), data.get("quiet_until")]
            if any(h not in (None, "") and not 0 <= int(h) <= 23 for h in hours):
                raise BusinessRuleViolation("Quiet hours are whole hours from 0 to 23.")
            pref.quiet_from = int(hours[0]) if hours[0] not in (None, "") else None
            pref.quiet_until = int(hours[1]) if hours[1] not in (None, "") else None
            pref.digest = bool(data.get("digest", pref.digest))
            pref.save()
        return Response(
            {"quiet_from": pref.quiet_from, "quiet_until": pref.quiet_until, "digest": pref.digest}
        )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": services.unread_count(request.user)})


class PushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)


class PushSubscriptionSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=500)
    keys = PushKeysSerializer()


class PushSubscriptionView(ContextBindingMixin, APIView):
    """Register (POST) or remove (DELETE) this browser for push notifications."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PushSubscriptionSerializer, responses={204: None}, tags=["notifications"]
    )
    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # A device belongs to whoever signed in on it last.
        PushSubscription.objects.update_or_create(
            endpoint=data["endpoint"],
            defaults={
                "user": request.user,
                "p256dh": data["keys"]["p256dh"],
                "auth": data["keys"]["auth"],
                "user_agent": request.headers.get("User-Agent", "")[:255],
            },
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=PushSubscriptionSerializer, responses={204: None}, tags=["notifications"]
    )
    def delete(self, request):
        endpoint = request.data.get("endpoint", "")
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
