from django.contrib import admin

from .models import RiderProfile, SavedPlace


class SavedPlaceInline(admin.TabularInline):
    model = SavedPlace
    extra = 0


@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "rating", "completed_trips", "referral_code", "is_blocked"]
    list_filter = ["is_blocked"]
    search_fields = ["user__email", "user__first_name", "user__last_name", "referral_code"]
    raw_id_fields = ["user", "referred_by"]
    inlines = [SavedPlaceInline]
