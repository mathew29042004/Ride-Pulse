"""Manager workspace API: /work/tasks, /work/meetings, /work/team, /work/dashboard."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import StaffProfile
from apps.accounts.roles import Cap
from apps.core.api import BaseViewSet

from . import scorecards, services
from .models import (
    OPEN_TASK_STATUSES,
    Meeting,
    MeetingAttendee,
    Priority,
    TaskComment,
    TaskStatus,
    WorkTask,
)

WORK = {"*": Cap.WORK_USE}


class TaskCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", default="", read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "kind", "body", "author", "author_name", "created_at"]


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source="assignee.get_full_name", read_only=True)
    assigned_by_name = serializers.CharField(source="assigned_by.get_full_name", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_overdue = serializers.SerializerMethodField()
    awaiting_update = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField()
    meeting_title = serializers.CharField(source="meeting.title", default=None, read_only=True)

    class Meta:
        model = WorkTask
        fields = [
            "id",
            "number",
            "title",
            "description",
            "assignee",
            "assignee_name",
            "assigned_by",
            "assigned_by_name",
            "priority",
            "priority_label",
            "status",
            "status_label",
            "due_at",
            "target",
            "progress",
            "batch",
            "meeting",
            "meeting_title",
            "started_at",
            "completed_at",
            "is_overdue",
            "awaiting_update",
            "mine",
            "created_at",
        ]

    def get_is_overdue(self, task) -> bool:
        from django.utils import timezone

        return task.is_open and task.due_at < timezone.now()

    def get_awaiting_update(self, task) -> bool:
        return task.is_open and services.pending_status_requests(task)

    def get_mine(self, task) -> bool:
        return task.assignee_id == self.context["request"].user.pk


class TaskDetailSerializer(TaskSerializer):
    comments = TaskCommentSerializer(many=True, read_only=True)

    class Meta(TaskSerializer.Meta):
        fields = [*TaskSerializer.Meta.fields, "comments"]


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True)
    assignee_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    whole_team = serializers.BooleanField(default=False)
    priority = serializers.ChoiceField(choices=Priority.choices, default=Priority.NORMAL)
    due_at = serializers.DateTimeField()
    target = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class TaskUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[TaskStatus.IN_PROGRESS, TaskStatus.DONE], required=False
    )
    progress = serializers.IntegerField(required=False, min_value=0)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class TaskManageSerializer(serializers.Serializer):
    cancel = serializers.BooleanField(default=False)
    assignee_id = serializers.IntegerField(required=False)
    due_at = serializers.DateTimeField(required=False)


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class TaskViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Tasks given to me, given by me, or inside my team.

    ``?scope=mine`` (assigned to me), ``given`` (I assigned), ``team`` (everyone below me);
    ``?state=open|overdue|done``."""

    capabilities = WORK
    search_fields = ["title", "number", "assignee__first_name", "assignee__last_name"]

    def get_serializer_class(self):
        return TaskDetailSerializer if self.action == "retrieve" else TaskSerializer

    def get_queryset(self):
        from django.utils import timezone

        if getattr(self, "swagger_fake_view", False):
            return WorkTask.objects.none()
        user = self.request.user
        tasks = services.visible_tasks(user).select_related("assignee", "assigned_by", "meeting")
        scope = self.request.query_params.get("scope")
        if scope == "mine":
            tasks = tasks.filter(assignee=user)
        elif scope == "given":
            tasks = tasks.filter(assigned_by=user)
        elif scope == "team":
            tasks = tasks.exclude(assignee=user)
        state = self.request.query_params.get("state")
        if state == "open":
            tasks = tasks.filter(status__in=OPEN_TASK_STATUSES)
        elif state == "overdue":
            tasks = tasks.filter(status__in=OPEN_TASK_STATUSES, due_at__lt=timezone.now())
        elif state == "done":
            tasks = tasks.filter(status=TaskStatus.DONE).order_by("-completed_at")
        if self.action == "retrieve":
            tasks = tasks.prefetch_related("comments__author")
        return tasks

    def _detail(self, task, code=status.HTTP_200_OK):
        task = self.get_queryset().get(pk=task.pk)
        return Response(
            TaskDetailSerializer(task, context={"request": self.request}).data, status=code
        )

    @extend_schema(request=TaskCreateSerializer, responses={201: TaskSerializer(many=True)})
    def create(self, request):
        data = TaskCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tasks = services.create_tasks(manager=request.user, **data.validated_data)
        return Response(
            TaskSerializer(tasks, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=TaskUpdateSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def update_status(self, request, pk=None):
        data = TaskUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._detail(
            services.update_task(self.get_object(), user=request.user, **data.validated_data)
        )

    @extend_schema(request=TaskManageSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def manage(self, request, pk=None):
        data = TaskManageSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._detail(
            services.reassign_or_cancel(self.get_object(), user=request.user, **data.validated_data)
        )

    @extend_schema(request=CommentSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        data = CommentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        task = self.get_object()
        services.comment(task, user=request.user, body=data.validated_data["body"])
        return self._detail(task)

    @extend_schema(request=None, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def ask_status(self, request, pk=None):
        task = self.get_object()
        services.ask_status(task, user=request.user)
        return self._detail(task)


class AttendeeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.get_full_name", read_only=True)
    response_label = serializers.CharField(source="get_response_display", read_only=True)

    class Meta:
        model = MeetingAttendee
        fields = ["user", "name", "response", "response_label", "attended"]


class MeetingSerializer(serializers.ModelSerializer):
    organizer_name = serializers.CharField(source="organizer.get_full_name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    attendees = AttendeeSerializer(many=True, read_only=True)
    my_response = serializers.SerializerMethodField()
    action_items = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = Meeting
        fields = [
            "id",
            "number",
            "title",
            "agenda",
            "organizer",
            "organizer_name",
            "starts_at",
            "duration_minutes",
            "status",
            "status_label",
            "notes",
            "repeats_daily",
            "attendees",
            "my_response",
            "action_items",
        ]

    def get_my_response(self, meeting) -> str | None:
        me = self.context["request"].user.pk
        return next((a.response for a in meeting.attendees.all() if a.user_id == me), None)


class MeetingCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    agenda = serializers.CharField(required=False, allow_blank=True)
    starts_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(default=15)
    attendee_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    whole_team = serializers.BooleanField(default=False)
    repeats_daily = serializers.BooleanField(default=False)


class ActionItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    assignee_id = serializers.IntegerField()
    due_at = serializers.DateTimeField(required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, default=Priority.NORMAL)


class MeetingCompleteSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)
    present_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    action_items = ActionItemSerializer(many=True, required=False)


class MeetingRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class CancelMeetingSerializer(serializers.Serializer):
    whole_series = serializers.BooleanField(default=False)


class MeetingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    """Meetings I organise or am invited to (``?when=upcoming|past``)."""

    capabilities = WORK
    serializer_class = MeetingSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Meeting.objects.none()
        meetings = services.visible_meetings(self.request.user).select_related("organizer")
        meetings = meetings.prefetch_related(
            "attendees__user", "action_items__assignee", "action_items__assigned_by"
        )
        when = self.request.query_params.get("when")
        if when == "upcoming":
            meetings = meetings.filter(status="SCHEDULED")
        elif when == "past":
            meetings = meetings.exclude(status="SCHEDULED").order_by("-starts_at")
        return meetings

    def _detail(self, meeting, code=status.HTTP_200_OK):
        meeting = self.get_queryset().get(pk=meeting.pk)
        return Response(
            MeetingSerializer(meeting, context={"request": self.request}).data, status=code
        )

    @extend_schema(request=MeetingCreateSerializer, responses={201: MeetingSerializer})
    def create(self, request):
        data = MeetingCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        meeting = services.schedule_meeting(organizer=request.user, **data.validated_data)
        return self._detail(meeting, status.HTTP_201_CREATED)

    @extend_schema(request=MeetingRespondSerializer, responses=MeetingSerializer)
    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        data = MeetingRespondSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        meeting = self.get_object()
        services.respond(meeting, user=request.user, accept=data.validated_data["accept"])
        return self._detail(meeting)

    @extend_schema(request=MeetingCompleteSerializer, responses=MeetingSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        data = MeetingCompleteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        meeting, _ = services.complete_meeting(
            self.get_object(), user=request.user, **data.validated_data
        )
        return self._detail(meeting)

    @extend_schema(request=CancelMeetingSerializer, responses=MeetingSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        data = CancelMeetingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        meeting = services.cancel_meeting(
            self.get_object(), user=request.user, **data.validated_data
        )
        return self._detail(meeting)


class WorkTeamViewSet(BaseViewSet):
    """People I can give work to, and the manager dashboard with scorecards."""

    capabilities = WORK

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def people(self, request):
        team = services.team_of(request.user)
        direct = services.direct_reports(request.user)
        profiles = (
            StaffProfile.objects.filter(user_id__in=team)
            .select_related("user", "city")
            .order_by("department", "user__first_name")
        )
        return Response(
            [
                {
                    "id": p.user_id,
                    "name": p.user.get_full_name(),
                    "title": p.title,
                    "department": p.get_department_display(),
                    "city": p.city.name if p.city else p.state,
                    "direct": p.user_id in direct,
                }
                for p in profiles
            ]
        )

    @extend_schema(
        parameters=[OpenApiParameter("days", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        days = request.query_params.get("days", "7")
        days = int(days) if days.isdigit() and 1 <= int(days) <= 90 else 7
        return Response(scorecards.scorecards(request.user, days=days))


# --- Shifts and leave -------------------------------------------------------------------------


class GenerateSerializer(serializers.Serializer):
    state = serializers.CharField(max_length=60)
    week_start = serializers.DateField()
    replace = serializers.BooleanField(default=False)


class LeaveRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["CASUAL", "SICK", "EARNED"])
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class DecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


def _leave_row(leave) -> dict:
    return {
        "id": leave.pk,
        "user_id": leave.user_id,
        "name": leave.user.get_full_name(),
        "kind": leave.kind,
        "kind_label": leave.get_kind_display(),
        "starts_on": leave.starts_on,
        "ends_on": leave.ends_on,
        "days": (leave.ends_on - leave.starts_on).days + 1,
        "reason": leave.reason,
        "status": leave.status,
        "status_label": leave.get_status_display(),
        "note": leave.note,
        "decided_by": leave.decided_by.get_full_name() if leave.decided_by_id else None,
    }


class RosterViewSet(BaseViewSet):
    """Support rosters by state and week; leave requests and approvals."""

    capabilities = {"*": Cap.WORK_USE, "generate": Cap.TEAM_VIEW}
    queryset = StaffProfile.objects.none()

    @extend_schema(
        parameters=[OpenApiParameter("state", str), OpenApiParameter("week", str, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def list(self, request):
        from datetime import date

        from django.utils import timezone

        from . import roster

        state = (
            request.query_params.get("state")
            or getattr(getattr(request.user, "staff_profile", None), "state", "")
            or "Tamil Nadu"
        )
        week = request.query_params.get("week")
        week_start = date.fromisoformat(week) if week else timezone.localdate()
        states = sorted(set(StaffProfile.objects.exclude(state="").values_list("state", flat=True)))
        return Response({**roster.week_view(state, week_start), "states": states})

    @extend_schema(request=GenerateSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def generate(self, request):
        from . import roster

        data = GenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(roster.generate_week(**data.validated_data))

    @extend_schema(methods=["GET"], responses={200: OpenApiTypes.OBJECT})
    @extend_schema(
        methods=["POST"], request=LeaveRequestSerializer, responses={201: OpenApiTypes.OBJECT}
    )
    @action(detail=False, methods=["get", "post"])
    def leave(self, request):
        from . import roster
        from .models import LeaveRequest, LeaveStatus
        from .services import team_of

        if request.method == "POST":
            data = LeaveRequestSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            leave = roster.request_leave(request.user, **data.validated_data)
            return Response(_leave_row(leave), status=status.HTTP_201_CREATED)
        mine = LeaveRequest.objects.filter(user=request.user).select_related("user", "decided_by")[
            :20
        ]
        to_decide = LeaveRequest.objects.filter(
            user_id__in=team_of(request.user), status=LeaveStatus.PENDING
        ).select_related("user", "decided_by")[:50]
        return Response(
            {"mine": [_leave_row(x) for x in mine], "to_decide": [_leave_row(x) for x in to_decide]}
        )

    @extend_schema(request=DecideSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path=r"leave/(?P<leave_id>\d+)/decide")
    def decide(self, request, leave_id=None):
        from django.shortcuts import get_object_or_404

        from . import roster
        from .models import LeaveRequest

        data = DecideSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        leave = get_object_or_404(LeaveRequest.objects.select_related("user"), pk=leave_id)
        return Response(roster.decide(leave, manager=request.user, **data.validated_data))
