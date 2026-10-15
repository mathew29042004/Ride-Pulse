from django.contrib import admin

from .models import Meeting, MeetingAttendee, TaskComment, WorkTask


class CommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0


@admin.register(WorkTask)
class WorkTaskAdmin(admin.ModelAdmin):
    list_display = ["number", "title", "assignee", "assigned_by", "priority", "status", "due_at"]
    list_filter = ["status", "priority"]
    search_fields = ["number", "title"]
    raw_id_fields = ["assignee", "assigned_by", "meeting"]
    inlines = [CommentInline]


class AttendeeInline(admin.TabularInline):
    model = MeetingAttendee
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["number", "title", "organizer", "starts_at", "status", "repeats_daily"]
    list_filter = ["status", "repeats_daily"]
    raw_id_fields = ["organizer"]
    inlines = [AttendeeInline]
