from django.contrib import admin

from .models import FareRule, PromoCode, PromoRedemption, RideType, SurgeOverride, SurgeSnapshot


@admin.register(RideType)
class RideTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "seats", "sort_order", "is_active"]


@admin.register(FareRule)
class FareRuleAdmin(admin.ModelAdmin):
    list_display = [
        "city",
        "ride_type",
        "base_fare",
        "per_km",
        "per_minute",
        "minimum_fare",
        "is_active",
    ]
    list_filter = ["city", "ride_type"]


@admin.register(SurgeSnapshot)
class SurgeSnapshotAdmin(admin.ModelAdmin):
    list_display = ["zone", "multiplier", "demand", "supply", "computed_at"]
    list_filter = ["zone__city"]


@admin.register(SurgeOverride)
class SurgeOverrideAdmin(admin.ModelAdmin):
    list_display = ["zone", "multiplier", "starts_at", "ends_at", "reason"]


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "discount_type", "value", "max_discount", "valid_until", "is_active"]
    list_filter = ["discount_type", "is_active", "city"]
    search_fields = ["code", "description"]


@admin.register(PromoRedemption)
class PromoRedemptionAdmin(admin.ModelAdmin):
    list_display = ["promo", "rider", "trip", "amount", "created_at"]
    raw_id_fields = ["rider", "trip"]
