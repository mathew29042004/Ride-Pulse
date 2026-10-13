from django.contrib import admin

from .models import Trip, TripEvent, TripOffer, TripRating


class TripEventInline(admin.TabularInline):
    model = TripEvent
    extra = 0
    readonly_fields = ["kind", "from_status", "to_status", "actor", "message", "created_at"]
    can_delete = False


class TripOfferInline(admin.TabularInline):
    model = TripOffer
    extra = 0
    readonly_fields = [
        "driver",
        "status",
        "offered_at",
        "responded_at",
        "distance_km",
        "eta_minutes",
    ]
    can_delete = False


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = [
        "trip_number",
        "status",
        "city",
        "ride_type",
        "rider",
        "driver",
        "fare_total",
        "requested_at",
    ]
    list_filter = ["status", "city", "ride_type", "payment_method", "payment_status"]
    search_fields = ["trip_number", "rider__user__email", "driver__user__email"]
    raw_id_fields = ["rider", "driver", "vehicle", "promo"]
    date_hierarchy = "requested_at"
    readonly_fields = ["fare_estimate", "fare_breakdown", "otp"]
    inlines = [TripOfferInline, TripEventInline]


@admin.register(TripRating)
class TripRatingAdmin(admin.ModelAdmin):
    list_display = ["trip", "direction", "stars", "created_at"]
    list_filter = ["direction", "stars"]
    raw_id_fields = ["trip"]
