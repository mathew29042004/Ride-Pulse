from django.contrib import admin

from .models import DailyBriefing, DemandNudge, FraudCase, OpsAlert


@admin.register(OpsAlert)
class OpsAlertAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "city", "severity", "status", "owner", "created_at"]
    list_filter = ["kind", "status", "severity"]


@admin.register(FraudCase)
class FraudCaseAdmin(admin.ModelAdmin):
    list_display = ["number", "kind", "driver", "rider", "score", "status", "created_at"]
    list_filter = ["kind", "status"]
    raw_id_fields = ["driver", "rider", "reviewed_by"]


admin.site.register(DailyBriefing)
admin.site.register(DemandNudge)
