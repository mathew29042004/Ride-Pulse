"""REST API v1 routes."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounts import api as accounts
from apps.analytics import api as analytics
from apps.audit.api import AuditLogViewSet
from apps.drivers import api as drivers
from apps.geo import api as geo
from apps.notifications.api import NotificationViewSet, PushSubscriptionView
from apps.payments import api as payments
from apps.pricing import api as pricing
from apps.riders import api as riders
from apps.rides import api as rides
from apps.support import api as support

router = DefaultRouter()
router.register("cities", geo.CityViewSet, basename="city")
router.register("ride-types", pricing.RideTypeViewSet, basename="ride-type")
router.register("fare-rules", pricing.FareRuleViewSet, basename="fare-rule")
router.register("surge", pricing.SurgeViewSet, basename="surge")
router.register("promos", pricing.PromoCodeViewSet, basename="promo")
router.register("price-alerts", pricing.PriceAlertViewSet, basename="price-alert")
router.register("trips", rides.TripViewSet, basename="trip")
router.register("scheduled-rides", rides.ScheduledRideViewSet, basename="scheduled-ride")
router.register("fare-splits", rides.FareSplitViewSet, basename="fare-split")
router.register("ride-checks", rides.RideCheckViewSet, basename="ride-check")
router.register("rider", riders.RiderProfileViewSet, basename="rider-self")
router.register("rider/places", riders.SavedPlaceViewSet, basename="saved-place")
router.register("rider/contacts", riders.TrustedContactViewSet, basename="trusted-contact")
router.register("team", accounts.TeamViewSet, basename="team")
router.register("riders", riders.RiderViewSet, basename="rider")
router.register("driver", drivers.DriverAppViewSet, basename="driver-self")
router.register("drivers", drivers.DriverViewSet, basename="driver")
router.register("wallet", payments.WalletViewSet, basename="wallet")
router.register("payments", payments.PaymentViewSet, basename="payment")
router.register("payouts", payments.PayoutViewSet, basename="payout")
router.register("support/tickets", support.TicketViewSet, basename="ticket")
router.register("safety/incidents", support.IncidentViewSet, basename="incident")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("staff/users", accounts.StaffUserViewSet, basename="staff-user")

auth_urls = [
    path("token/", accounts.TokenView.as_view(), name="token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("logout/", accounts.LogoutView.as_view(), name="logout"),
    path("me/", accounts.MeView.as_view(), name="me"),
    path("register/rider/", accounts.RegisterRiderView.as_view(), name="register-rider"),
    path("register/driver/", accounts.RegisterDriverView.as_view(), name="register-driver"),
    path("otp/request/", accounts.OtpRequestView.as_view(), name="otp-request"),
    path("otp/verify/", accounts.OtpVerifyView.as_view(), name="otp-verify"),
    path("otp/signup/", accounts.OtpSignupView.as_view(), name="otp-signup"),
]

analytics_urls = [
    path("overview/", analytics.OverviewView.as_view(), name="analytics-overview"),
    path("timeseries/", analytics.TimeSeriesView.as_view(), name="analytics-timeseries"),
    path("breakdown/", analytics.BreakdownView.as_view(), name="analytics-breakdown"),
    path("trips.csv", analytics.TripExportView.as_view(), name="analytics-trips-csv"),
    path("warehouse/", analytics.WarehouseInsightsView.as_view(), name="analytics-warehouse"),
]

urlpatterns = [
    path("auth/", include(auth_urls)),
    path("analytics/", include(analytics_urls)),
    path("fares/estimate/", pricing.FareEstimateView.as_view(), name="fare-estimate"),
    path("fares/packages/", rides.PackageQuoteView.as_view(), name="fare-packages"),
    path("fares/nearby-drivers/", rides.NearbyDriversView.as_view(), name="nearby-drivers"),
    path("track/<str:token>/", rides.SharedTripView.as_view(), name="shared-trip"),
    path("places/", geo.PlaceSearchView.as_view(), name="places"),
    path("ops/live/", rides.LiveOpsView.as_view(), name="ops-live"),
    path("ops/dispatch/sweep/", rides.DispatchSweepView.as_view(), name="dispatch-sweep"),
    path("ledger/", payments.LedgerView.as_view(), name="ledger"),
    path("push/subscription/", PushSubscriptionView.as_view(), name="push-subscription"),
    path(
        "payments/razorpay/webhook/",
        payments.RazorpayWebhookView.as_view(),
        name="razorpay-webhook",
    ),
    path("", include(router.urls)),
]
