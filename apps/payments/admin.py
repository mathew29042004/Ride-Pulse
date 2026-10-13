from django.contrib import admin

from .models import LedgerEntry, LedgerTransaction, Payment, Payout, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ["user", "balance", "updated_at"]
    search_fields = ["user__email"]
    raw_id_fields = ["user"]
    readonly_fields = ["balance"]


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    readonly_fields = ["account", "wallet", "amount"]
    can_delete = False


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(admin.ModelAdmin):
    list_display = ["reference", "kind", "trip", "description", "created_at"]
    list_filter = ["kind"]
    search_fields = ["reference", "description"]
    inlines = [LedgerEntryInline]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["reference", "user", "purpose", "method", "amount", "status", "created_at"]
    list_filter = ["status", "method", "purpose"]
    search_fields = ["reference", "gateway_reference", "user__email"]
    raw_id_fields = ["user", "trip"]


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["payout_number", "driver", "amount", "status", "period_end", "paid_at"]
    list_filter = ["status"]
    raw_id_fields = ["driver"]
