from django.contrib import admin

from .models import SafetyIncident, SupportTicket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = [
        "ticket_number",
        "subject",
        "category",
        "priority",
        "status",
        "assigned_to",
        "sla_due_at",
    ]
    list_filter = ["status", "priority", "category", "escalated"]
    search_fields = ["ticket_number", "subject", "raised_by__email"]
    raw_id_fields = ["raised_by", "trip", "assigned_to"]
    inlines = [TicketMessageInline]


@admin.register(SafetyIncident)
class SafetyIncidentAdmin(admin.ModelAdmin):
    list_display = ["incident_number", "trip", "status", "created_at", "acknowledged_at"]
    list_filter = ["status"]
    raw_id_fields = ["trip", "raised_by", "acknowledged_by", "ticket"]
