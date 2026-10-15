"""Ledger account names. Wallet accounts are ``wallet:<user id>``."""

PLATFORM_COMMISSION = "platform:commission"
PLATFORM_FEES = "platform:fees"
PLATFORM_PROMOTIONS = "platform:promotions"
PLATFORM_REFUNDS = "platform:refunds"
PLATFORM_SUBSCRIPTIONS = "platform:subscriptions"
GST_PAYABLE = "tax:gst_payable"
TDS_PAYABLE = "tax:tds_payable"  # income tax withheld from drivers (section 194-O)
GATEWAY = "external:gateway"
PAYOUTS_IN_TRANSIT = "external:payouts_in_transit"
INSURER = "external:insurer"  # partner insurer funding accident claims

PLATFORM_ACCOUNTS = (
    PLATFORM_COMMISSION,
    PLATFORM_FEES,
    PLATFORM_PROMOTIONS,
    PLATFORM_REFUNDS,
    PLATFORM_SUBSCRIPTIONS,
    GST_PAYABLE,
    TDS_PAYABLE,
    GATEWAY,
    PAYOUTS_IN_TRANSIT,
    INSURER,
)
