"""Ledger account names. Wallet accounts are ``wallet:<user id>``."""

PLATFORM_COMMISSION = "platform:commission"
PLATFORM_FEES = "platform:fees"
PLATFORM_PROMOTIONS = "platform:promotions"
PLATFORM_REFUNDS = "platform:refunds"
GST_PAYABLE = "tax:gst_payable"
GATEWAY = "external:gateway"
PAYOUTS_IN_TRANSIT = "external:payouts_in_transit"

PLATFORM_ACCOUNTS = (
    PLATFORM_COMMISSION,
    PLATFORM_FEES,
    PLATFORM_PROMOTIONS,
    PLATFORM_REFUNDS,
    GST_PAYABLE,
    GATEWAY,
    PAYOUTS_IN_TRANSIT,
)
