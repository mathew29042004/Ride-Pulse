from django.contrib import admin

from .models import (
    AirportQueueEntry,
    ChargingStation,
    DriverStatement,
    FleetMembership,
    FleetOwner,
    Quest,
    QuestProgress,
    ServiceRecord,
)


@admin.register(FleetOwner)
class FleetOwnerAdmin(admin.ModelAdmin):
    list_display = ["company_name", "city", "share_percent", "is_active"]
    raw_id_fields = ["user", "account_manager"]


@admin.register(Quest)
class QuestAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "city", "state", "status", "starts_at", "ends_at", "spent"]
    list_filter = ["status"]


@admin.register(DriverStatement)
class DriverStatementAdmin(admin.ModelAdmin):
    list_display = ["number", "driver", "week_start", "gross_fares", "tds_amount", "net_earnings"]
    raw_id_fields = ["driver"]


for model in (FleetMembership, ServiceRecord, ChargingStation, QuestProgress, AirportQueueEntry):
    admin.site.register(model)
