"""Team chat API (staff only): ``/api/v1/chat/…``."""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet
from apps.core.exceptions import ActionNotPermitted

from . import services
from .models import Conversation, Member, Message


class SendSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=services.MAX_BODY)


class DirectSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class GroupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    member_ids = serializers.ListField(child=serializers.IntegerField(), max_length=60)


class ThreadSerializer(serializers.Serializer):
    task_id = serializers.IntegerField(required=False)
    meeting_id = serializers.IntegerField(required=False)
    ticket_id = serializers.IntegerField(required=False)


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    body = serializers.CharField(max_length=services.MAX_BODY, required=False, allow_blank=True)


class ChatViewSet(BaseViewSet):
    capabilities = {"*": Cap.WORK_USE}
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = Conversation.objects.none()

    def _conversation(self, request, pk) -> Conversation:
        conversation = get_object_or_404(Conversation, pk=pk)
        if not Member.objects.filter(conversation=conversation, user=request.user).exists():
            raise ActionNotPermitted("You're not in this conversation.")
        return conversation

    def _summary(self, request, conversation) -> dict:
        return {
            "id": conversation.pk,
            "kind": conversation.kind,
            "title": services.title_for(conversation, request.user),
            "topic": conversation.topic,
            "task_id": conversation.task_id,
            "meeting_id": conversation.meeting_id,
            "ticket_id": conversation.ticket_id,
            "members": [
                {"id": m.user_id, "name": m.user.get_full_name()}
                for m in conversation.members.select_related("user").order_by("user__first_name")[
                    :200
                ]
            ],
        }

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        return Response(
            {
                "conversations": services.inbox(request.user),
                "unread": services.total_unread(request.user),
            }
        )

    @extend_schema(
        parameters=[OpenApiParameter("before", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        conversation = self._conversation(request, pk)
        rows = Message.objects.filter(conversation=conversation).select_related("author")
        if before := request.query_params.get("before"):
            rows = rows.filter(pk__lt=int(before))
        page = list(rows.order_by("-created_at", "-pk")[:50])[::-1]
        services.mark_read(conversation, request.user)
        return Response(
            {
                **self._summary(request, conversation),
                "messages": [services.message_row(m) for m in page],
                "more": len(page) == 50,
            }
        )

    @extend_schema(request=SendSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        conversation = self._conversation(request, pk)
        data = SendSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        message = services.send(conversation, request.user, data.validated_data["body"])
        return Response(services.message_row(message), status=status.HTTP_201_CREATED)

    @extend_schema(request=UploadSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def upload(self, request, pk=None):
        """Share a file (up to 10 MB), with an optional message."""
        conversation = self._conversation(request, pk)
        data = UploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        message = services.send(
            conversation,
            request.user,
            data.validated_data.get("body", ""),
            upload=data.validated_data["file"],
        )
        return Response(services.message_row(message), status=status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path=r"file/(?P<message_id>\d+)")
    def file(self, request, pk=None, message_id=None):
        conversation = self._conversation(request, pk)
        message = get_object_or_404(Message, pk=message_id, conversation=conversation)
        if not message.attachment:
            raise ActionNotPermitted("This message has no file.")
        return FileResponse(
            message.attachment.open("rb"),
            as_attachment=not message_row_is_image(message),
            filename=message.attachment_name,
        )

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def typing(self, request, pk=None):
        services.typing(self._conversation(request, pk), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[OpenApiParameter("q", str)],
        responses={200: OpenApiTypes.OBJECT},
        operation_id="chat_search",
    )
    @action(detail=False, methods=["get"])
    def search(self, request):
        return Response(services.search(request.user, request.query_params.get("q", "")))

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        services.mark_read(self._conversation(request, pk), request.user)
        return Response({"unread": services.total_unread(request.user)})

    @extend_schema(request=DirectSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def direct(self, request):
        data = DirectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        conversation = services.open_direct(request.user, data.validated_data["user_id"])
        return Response({"id": conversation.pk})

    @extend_schema(request=GroupSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def group(self, request):
        data = GroupSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        conversation = services.create_group(request.user, **data.validated_data)
        return Response({"id": conversation.pk}, status=status.HTTP_201_CREATED)

    @extend_schema(request=ThreadSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def thread(self, request):
        data = ThreadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        conversation = services.thread_for(request.user, **data.validated_data)
        return Response({"id": conversation.pk})

    @extend_schema(
        parameters=[OpenApiParameter("q", str, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def people(self, request):
        """Staff to start a conversation with (search by name, email or title)."""
        from django.db.models import Q

        q = (request.query_params.get("q") or "").strip()
        rows = services._staff().exclude(pk=request.user.pk).select_related("staff_profile")
        if q:
            rows = rows.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(staff_profile__title__icontains=q)
            )
        return Response(
            [
                {
                    "id": u.pk,
                    "name": u.get_full_name(),
                    "title": u.staff_profile.title,
                    "handle": u.email.split("@")[0],
                }
                for u in rows.order_by("first_name")[:30]
            ]
        )


def message_row_is_image(message) -> bool:
    return services._ext(message.attachment_name) in services.IMAGES
