from django.contrib import admin

from .models import OutboxEvent, SecurityEvent, WebhookDelivery, WebhookEndpoint


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ["topic", "aggregate", "created_at", "published_at"]
    list_filter = ["topic"]


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ["event", "endpoint", "status", "attempts", "next_attempt_at", "last_error"]
    list_filter = ["status"]


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ["kind", "email", "ip", "path", "created_at"]
    list_filter = ["kind"]


admin.site.register(WebhookEndpoint)
