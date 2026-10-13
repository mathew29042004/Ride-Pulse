from django.contrib import admin

from .models import DriverDocument, DriverProfile, DriverSession, Vehicle


class VehicleInline(admin.TabularInline):
    model = Vehicle
    extra = 0


class DocumentInline(admin.TabularInline):
    model = DriverDocument
    extra = 0
    fields = ["doc_type", "number_last4", "expires_on", "status", "reviewed_at"]
    readonly_fields = ["reviewed_at"]


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "city",
        "onboarding_status",
        "availability",
        "rating",
        "completed_trips",
        "safety_score",
    ]
    list_filter = ["city", "onboarding_status", "availability"]
    search_fields = ["user__email", "user__first_name", "user__last_name", "license_number"]
    raw_id_fields = ["user"]
    inlines = [VehicleInline, DocumentInline]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["registration_number", "make", "model", "ride_type", "driver", "is_active"]
    list_filter = ["ride_type", "is_active"]
    search_fields = ["registration_number", "driver__user__email"]
    raw_id_fields = ["driver"]


@admin.register(DriverSession)
class DriverSessionAdmin(admin.ModelAdmin):
    list_display = ["driver", "started_at", "ended_at"]
    raw_id_fields = ["driver"]
