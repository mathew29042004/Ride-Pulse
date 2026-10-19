"""Manager workspace API: /work/tasks, /work/meetings, /work/team, /work/dashboard."""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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


class CorrectionSerializer(serializers.Serializer):
    clock_in = serializers.DateTimeField(required=False, allow_null=True, default=None)
    clock_out = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=200)


class AttendanceViewSet(BaseViewSet):
    """Clock in and out, my month, the team board and corrections."""

    capabilities = {"*": Cap.WORK_USE}
    queryset = StaffProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="attendance_mine")
    def list(self, request):
        from . import attendance

        return Response(attendance.mine(request.user))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="clock-in")
    def clock_in(self, request):
        from . import attendance

        lat, lng = request.data.get("lat"), request.data.get("lng")
        attendance.clock_in(
            request.user,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
        )
        return Response(attendance.mine(request.user))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="clock-out")
    def clock_out(self, request):
        from . import attendance

        attendance.clock_out(request.user)
        note = str(request.data.get("handover", "")).strip()
        if note:
            from .culture import leave_handover

            leave_handover(request.user, note)
        return Response(attendance.mine(request.user))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def handovers(self, request):
        """Notes the previous shift left for my role and city (last 24 hours)."""
        from .culture import handovers_for

        return Response({"notes": handovers_for(request.user)})

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def handover(self, request):
        from .culture import leave_handover

        n = leave_handover(request.user, str(request.data.get("body", "")))
        return Response({"id": n.pk}, status=201)

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="attendance_team")
    @action(detail=False, methods=["get"])
    def team(self, request):
        from . import attendance

        return Response(attendance.team(request.user))

    @extend_schema(request=CorrectionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        from django.shortcuts import get_object_or_404

        from . import attendance

        data = CorrectionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        record = get_object_or_404(attendance.Attendance, pk=pk, user=request.user)
        record = attendance.request_correction(
            record,
            user=request.user,
            clock_in_at=v["clock_in"],
            clock_out_at=v["clock_out"],
            reason=v["reason"],
        )
        return Response(attendance.row(record))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        from django.shortcuts import get_object_or_404

        from . import attendance

        record = get_object_or_404(attendance.Attendance, pk=pk)
        record = attendance.decide_correction(
            record, manager=request.user, approve=bool(request.data.get("approve"))
        )
        return Response(attendance.row(record))


class MonthSerializer(serializers.Serializer):
    month = serializers.DateField()


class PaySerializer(MonthSerializer):
    bank_reference = serializers.CharField(max_length=40)


class SalarySerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    monthly_gross = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=10_000)
    pf = serializers.BooleanField(default=True)
    bank_account_last4 = serializers.CharField(
        max_length=4, required=False, allow_blank=True, default=""
    )


class PayrollViewSet(BaseViewSet):
    """HR: salaries, the monthly payroll run, approval and payment."""

    capabilities = {"*": Cap.PAYROLL_MANAGE}
    queryset = StaffProfile.objects.none()

    def _month(self, request):
        """The ``month`` asked for, or last month (the one usually being paid)."""
        from datetime import date, timedelta

        from django.utils import timezone

        raw = request.query_params.get("month") or request.data.get("month")
        if raw:
            return date.fromisoformat(str(raw)[:10]).replace(day=1)
        return (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)

    @extend_schema(
        parameters=[OpenApiParameter("month", str, required=False)],
        responses={200: OpenApiTypes.OBJECT},
        operation_id="payroll_summary",
    )
    def list(self, request):
        from . import payroll

        month = self._month(request)
        missing = StaffProfile.objects.filter(user__is_active=True, user__salary__isnull=True)
        return Response(
            {
                **payroll.summary(month),
                "without_salary": [
                    {"user_id": p.user_id, "name": p.user.get_full_name(), "title": p.title}
                    for p in missing.select_related("user")[:100]
                ],
            }
        )

    @extend_schema(request=MonthSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="run")
    def run_payroll(self, request):
        from . import payroll

        month = self._month(request)
        result = payroll.run(month, user=request.user)
        return Response({**result, **payroll.summary(month)})

    @extend_schema(request=MonthSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def approve(self, request):
        from . import payroll

        month = self._month(request)
        payroll.approve(month, user=request.user)
        return Response(payroll.summary(month))

    @extend_schema(request=PaySerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def pay(self, request):
        from . import payroll

        data = PaySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        month = data.validated_data["month"]
        payroll.mark_paid(
            month, user=request.user, bank_reference=data.validated_data["bank_reference"]
        )
        return Response(payroll.summary(month))

    @extend_schema(request=SalarySerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def salary(self, request):
        from django.utils import timezone

        from . import payroll

        data = SalarySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        profile = get_object_or_404(StaffProfile, user_id=v["user_id"])
        salary, _ = payroll.SalaryStructure.objects.update_or_create(
            user=profile.user,
            defaults={
                "monthly_gross": v["monthly_gross"],
                "pf": v["pf"],
                "bank_account_last4": v["bank_account_last4"],
                "effective_from": timezone.localdate().replace(day=1),
            },
        )
        return Response({"user_id": salary.user_id, "monthly_gross": salary.monthly_gross})


class PayslipViewSet(BaseViewSet):
    """Everyone: my payslips and their PDFs (HR can open anyone's)."""

    capabilities = {"*": Cap.WORK_USE}
    queryset = StaffProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="payslips_mine")
    def list(self, request):
        from . import payroll

        slips = payroll.Payslip.objects.filter(
            user=request.user,
            status__in=[payroll.PayslipStatus.APPROVED, payroll.PayslipStatus.PAID],
        ).select_related("user")[:24]
        salary = getattr(request.user, "salary", None)
        return Response(
            {
                "monthly_gross": salary.monthly_gross if salary else None,
                "payslips": [payroll.row(s) for s in slips],
            }
        )

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        from django.http import HttpResponse

        from apps.core.exceptions import ActionNotPermitted

        from . import payroll

        slip = get_object_or_404(payroll.Payslip, pk=pk)
        if slip.user_id != request.user.pk and not request.user.has_capability(Cap.PAYROLL_MANAGE):
            raise ActionNotPermitted("You can only open your own payslips.")
        response = HttpResponse(payroll.render_pdf(slip), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="payslip-{slip.month:%Y-%m}.pdf"'
        return response


class ExpenseSubmitSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=8)
    spent_on = serializers.DateField()
    amount = serializers.DecimalField(max_digits=9, decimal_places=2)
    description = serializers.CharField(max_length=200)
    receipt = serializers.FileField(required=False)


class ExpenseDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ExpenseViewSet(BaseViewSet):
    """My expense claims, and my team's to approve."""

    capabilities = {"*": Cap.WORK_USE}
    queryset = StaffProfile.objects.none()
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="expenses_overview")
    def list(self, request):
        from . import expenses
        from .services import team_of

        mine = expenses.ExpenseClaim.objects.filter(user=request.user).select_related(
            "user", "decided_by"
        )[:50]
        team = expenses.ExpenseClaim.objects.filter(
            user_id__in=team_of(request.user), status=expenses.ClaimStatus.SUBMITTED
        ).select_related("user")[:100]
        return Response(
            {
                "mine": [expenses.row(c) for c in mine],
                "to_approve": [expenses.row(c) for c in team],
                "categories": [
                    {"value": v, "label": label, "limit": expenses.POLICY[v]}
                    for v, label in expenses.ExpenseCategory.choices
                ],
            }
        )

    @extend_schema(request=ExpenseSubmitSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        from . import expenses

        data = ExpenseSubmitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        claim = expenses.submit(request.user, **data.validated_data)
        return Response(expenses.row(claim), status=status.HTTP_201_CREATED)

    @extend_schema(request=ExpenseDecisionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        from . import expenses

        data = ExpenseDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        claim = get_object_or_404(expenses.ExpenseClaim, pk=pk)
        return Response(
            expenses.row(expenses.decide(claim, manager=request.user, **data.validated_data))
        )

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        from django.http import FileResponse

        from apps.core.exceptions import ActionNotPermitted

        from . import expenses
        from .services import team_of

        claim = get_object_or_404(expenses.ExpenseClaim, pk=pk)
        allowed = claim.user_id == request.user.pk or claim.user_id in team_of(request.user)
        if not allowed and not request.user.has_capability(Cap.PAYROLL_MANAGE):
            raise ActionNotPermitted("You can't see this receipt.")
        if not claim.receipt:
            raise ActionNotPermitted("No receipt was attached.")
        return FileResponse(
            claim.receipt.open("rb"), filename=claim.receipt.name.rsplit("/", 1)[-1]
        )


class OffboardSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    reason = serializers.CharField(max_length=200)
    last_day = serializers.DateField(required=False)


class AccessDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["KEEP", "CHANGE", "REMOVE"])
    new_role = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AccessViewSet(BaseViewSet):
    """Access reviews (every manager reviews their team), offboarding and joiners (admins)."""

    capabilities = {"list": Cap.WORK_USE, "decide": Cap.WORK_USE, "*": Cap.USERS_MANAGE}
    queryset = StaffProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="access_overview")
    def list(self, request):
        from . import access

        review = access.AccessReview.objects.first()
        mine = (
            access.AccessReviewItem.objects.filter(review=review, reviewer=request.user)
            .select_related("subject__staff_profile", "reviewer", "review")
            .order_by("decision", "subject__first_name")
            if review
            else []
        )
        body = {
            "review": access.review_progress(review) if review else None,
            "mine": [access.item_row(i) for i in mine],
            "roles": access.STAFF_ROLES,
            "admin": request.user.has_capability(Cap.USERS_MANAGE),
        }
        if body["admin"]:
            body["joiners"] = access.joiners()
            body["leavers"] = [
                {
                    "name": o.user.get_full_name(),
                    "reason": o.reason,
                    "last_day": o.last_day,
                    "steps": o.steps,
                    "by": o.by.get_full_name() if o.by_id else None,
                }
                for o in access.Offboarding.objects.select_related("user", "by")[:20]
            ]
        return Response(body)

    @extend_schema(request=None, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def start(self, request):
        from . import access

        review = access.start_review(by=request.user)
        return Response(access.review_progress(review), status=status.HTTP_201_CREATED)

    @extend_schema(request=AccessDecisionSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        from . import access

        data = AccessDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        item = get_object_or_404(
            access.AccessReviewItem.objects.select_related("review", "subject"), pk=pk
        )
        return Response(
            access.item_row(access.decide(item, reviewer=request.user, **data.validated_data))
        )

    @extend_schema(request=OffboardSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def offboard(self, request):
        from apps.accounts.models import User

        from . import access

        data = OffboardSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = get_object_or_404(User, pk=v["user_id"])
        record = access.offboard(
            user, by=request.user, reason=v["reason"], last_day=v.get("last_day")
        )
        return Response({"name": user.get_full_name(), "steps": record.steps})


class SelfReviewSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000)
    rating = serializers.IntegerField(min_value=1, max_value=5)


class AppraisalRatingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=4000)


class AppraisalViewSet(BaseViewSet):
    """Half-yearly appraisals: my own, my team's, and (admins) the cycle."""

    capabilities = {"start": Cap.USERS_MANAGE, "close": Cap.USERS_MANAGE, "*": Cap.WORK_USE}
    queryset = StaffProfile.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, operation_id="appraisals_overview")
    def list(self, request):
        from . import appraisals

        cycle = appraisals.AppraisalCycle.objects.first()
        rows = appraisals.Appraisal.objects.filter(cycle=cycle).select_related(
            "employee", "manager", "cycle"
        )
        body = {
            "cycle": {"id": cycle.pk, "name": cycle.name, "closed": bool(cycle.closed_at)}
            if cycle
            else None,
            "mine": [appraisals.row(a) for a in rows.filter(employee=request.user)],
            "team": [appraisals.row(a) for a in rows.filter(manager=request.user)],
            "raises": appraisals.RAISE,
            "admin": request.user.has_capability(Cap.USERS_MANAGE),
        }
        if body["admin"] and cycle:
            from django.db.models import Count

            body["progress"] = dict(rows.values_list("status").annotate(n=Count("id")))
        return Response(body)

    @extend_schema(request=None, responses={201: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def start(self, request):
        from . import appraisals

        cycle = appraisals.start(by=request.user)
        return Response({"name": cycle.name}, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def close(self, request):
        from . import appraisals

        cycle = get_object_or_404(appraisals.AppraisalCycle, closed_at__isnull=True)
        return Response(appraisals.close(cycle, by=request.user))

    @extend_schema(request=SelfReviewSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="self")
    def self_review(self, request, pk=None):
        from . import appraisals

        data = SelfReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        a = get_object_or_404(appraisals.Appraisal, pk=pk)
        return Response(
            appraisals.row(appraisals.self_review(a, user=request.user, **data.validated_data))
        )

    @extend_schema(request=AppraisalRatingSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def rate(self, request, pk=None):
        from . import appraisals

        data = AppraisalRatingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        a = get_object_or_404(appraisals.Appraisal, pk=pk)
        return Response(
            appraisals.row(appraisals.rate(a, manager=request.user, **data.validated_data))
        )
