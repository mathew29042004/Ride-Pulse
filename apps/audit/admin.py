from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "entity_type", "entity_label", "message"]
    list_filter = ["action", "entity_type"]
    search_fields = ["entity_label", "entity_id", "message", "request_id"]
    date_hierarchy = "created_at"
    list_select_related = ["actor"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
