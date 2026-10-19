"""Manager workspace: tasks, daily meetings and check-ins that flow down the org chart."""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class TaskStatus(models.TextChoices):
    TODO = "TODO", "To do"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    DONE = "DONE", "Done"
    CANCELLED = "CANCELLED", "Cancelled"


OPEN_TASK_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)


class WorkTask(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks_assigned"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks"
    )
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=12, choices=TaskStatus.choices, default=TaskStatus.TODO)
    due_at = models.DateTimeField()
    # Optional measurable target ("verify 20 drivers"): progress counts towards it.
    target = models.PositiveIntegerField(null=True, blank=True)
    progress = models.PositiveIntegerField(default=0)
    # One "assign to my team" request creates a task per person, sharing a batch id.
    batch = models.CharField(max_length=20, blank=True, db_index=True)
    meeting = models.ForeignKey(
        "Meeting", null=True, blank=True, on_delete=models.SET_NULL, related_name="action_items"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    overdue_flagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_at", "pk"]
        indexes = [models.Index(fields=["assignee", "status"], name="task_assignee_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target__isnull=True) | models.Q(target__gt=0),
                name="task_target_positive",
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.title}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_TASK_STATUSES


class CommentKind(models.TextChoices):
    COMMENT = "COMMENT", "Comment"
    STATUS_REQUEST = "STATUS_REQUEST", "Status request"
    UPDATE = "UPDATE", "Status update"
    SYSTEM = "SYSTEM", "System"


class TaskComment(models.Model):
    task = models.ForeignKey(WorkTask, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=16, choices=CommentKind.choices, default=CommentKind.COMMENT)
    body = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.task_id} {self.kind}"


class MeetingStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    DONE = "DONE", "Done"
    CANCELLED = "CANCELLED", "Cancelled"


class Meeting(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=160)
    agenda = models.TextField(blank=True)
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="meetings_organized"
    )
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=15)
    status = models.CharField(
        max_length=10, choices=MeetingStatus.choices, default=MeetingStatus.SCHEDULED
    )
    notes = models.TextField(blank=True)
    # A daily stand-up: the next day's meeting is created automatically (weekdays).
    repeats_daily = models.BooleanField(default=False)
    series = models.CharField(max_length=20, blank=True, db_index=True)

    class Meta:
        ordering = ["starts_at", "pk"]

    def __str__(self) -> str:
        return f"{self.number} {self.title}"


class AttendeeResponse(models.TextChoices):
    INVITED = "INVITED", "Invited"
    ACCEPTED = "ACCEPTED", "Going"
    DECLINED = "DECLINED", "Can't make it"


class MeetingAttendee(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="attendees")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    response = models.CharField(
        max_length=10, choices=AttendeeResponse.choices, default=AttendeeResponse.INVITED
    )
    attended = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["meeting", "user"], name="one_invite_per_person")
        ]

    def __str__(self) -> str:
        return f"{self.meeting_id} {self.user_id} {self.response}"


# --- Shifts and leave -------------------------------------------------------------------------


class ShiftSlot(models.TextChoices):
    MORNING = "MORNING", "Morning (6 am – 2 pm)"
    EVENING = "EVENING", "Evening (2 pm – 10 pm)"
    NIGHT = "NIGHT", "Night (10 pm – 6 am)"


class Shift(models.Model):
    """One person on one shift on one day (support desks today; any team can use it)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shifts"
    )
    day = models.DateField(db_index=True)
    slot = models.CharField(max_length=7, choices=ShiftSlot.choices)
    state = models.CharField(max_length=60, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    covering_for = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["day", "starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "day", "slot"], name="one_shift_per_slot")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.day} {self.slot}"


class LeaveKind(models.TextChoices):
    CASUAL = "CASUAL", "Casual leave"
    SICK = "SICK", "Sick leave"
    EARNED = "EARNED", "Earned leave"


class LeaveStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting for approval"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Not approved"
    CANCELLED = "CANCELLED", "Cancelled"


class LeaveRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave"
    )
    kind = models.CharField(max_length=6, choices=LeaveKind.choices)
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=9, choices=LeaveStatus.choices, default=LeaveStatus.PENDING
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-starts_on"]

    def __str__(self) -> str:
        return f"{self.user_id} {self.kind} {self.starts_on}–{self.ends_on}"


from .access import AccessReview, AccessReviewItem, Offboarding  # noqa: E402,F401  (registers the models)
from .appraisals import Appraisal, AppraisalCycle  # noqa: E402,F401  (registers the models)
from .attendance import Attendance  # noqa: E402,F401  (registers the model)
from .expenses import ExpenseClaim  # noqa: E402,F401  (registers the model)
from .payroll import Payslip, SalaryStructure  # noqa: E402,F401  (registers the models)
