from django.contrib import admin

from .models import City, Zone


class ZoneInline(admin.TabularInline):
    model = Zone
    extra = 0


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "radius_km", "fare_multiplier", "is_active"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [ZoneInline]


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "radius_km", "is_airport", "demand_weight"]
    list_filter = ["city", "is_airport"]
