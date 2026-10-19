"""REST API v1 routes."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounts import api as accounts
from apps.analytics import api as analytics
from apps.announcements import api as announcements
from apps.audit.api import AuditLogViewSet
from apps.chat import api as chat
from apps.compliance import api as compliance
from apps.drivers import api as drivers
from apps.experiments import api as experiments
from apps.fleet import api as fleet
from apps.geo import api as geo
from apps.intelligence import api as intelligence
from apps.notifications.api import NotificationViewSet, PushSubscriptionView
from apps.payments import api as payments
from apps.pricing import api as pricing
from apps.reliability import api as reliability
from apps.riders import api as riders
from apps.rides import api as rides
from apps.support import api as support
from apps.tours import api as tours
from apps.trust import api as trust
from apps.workspace import api as workspace

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
router.register("rider/profiles", riders.PaymentProfileViewSet, basename="payment-profile")
router.register("rider/teens", riders.TeenViewSet, basename="rider-teen")
router.register("rider/business", riders.CorporateViewSet, basename="rider-business")
router.register("rider/commute", riders.CommuteViewSet, basename="rider-commute")
router.register("team", accounts.TeamViewSet, basename="team")
router.register("work/tasks", workspace.TaskViewSet, basename="work-task")
router.register("work/meetings", workspace.MeetingViewSet, basename="work-meeting")
router.register("work/roster", workspace.RosterViewSet, basename="work-roster")
router.register("work/attendance", workspace.AttendanceViewSet, basename="work-attendance")
router.register("work/payroll", workspace.PayrollViewSet, basename="work-payroll")
router.register("work/payslips", workspace.PayslipViewSet, basename="work-payslip")
router.register("work/expenses", workspace.ExpenseViewSet, basename="work-expense")
router.register("work/access", workspace.AccessViewSet, basename="work-access")
router.register("work/appraisals", workspace.AppraisalViewSet, basename="work-appraisal")
router.register("work", workspace.WorkTeamViewSet, basename="work")
router.register("intel/alerts", intelligence.AlertViewSet, basename="intel-alert")
router.register("intel/fraud", intelligence.FraudCaseViewSet, basename="intel-fraud")
router.register("intel", intelligence.InsightsViewSet, basename="intel")
router.register("fleet", fleet.FleetOwnerPortalViewSet, basename="fleet-owner")
router.register("ops/fleet", fleet.FleetOpsViewSet, basename="ops-fleet")
router.register("platform", reliability.PlatformViewSet, basename="platform")
router.register("me", trust.MyTrustViewSet, basename="me-trust")
router.register("help", trust.HelpViewSet, basename="help")
router.register("nps", trust.NpsViewSet, basename="nps")
router.register("ops/trust", trust.TrustOpsViewSet, basename="ops-trust")
router.register("ops/experiments", experiments.ExperimentsOpsViewSet, basename="ops-experiments")
router.register("ops/tours", tours.TourOpsViewSet, basename="ops-tours")
router.register("tours", tours.TourViewSet, basename="tour")
router.register("chat", chat.ChatViewSet, basename="chat")
router.register("chat-messages", chat.MessageActionsViewSet, basename="chat-messages")
router.register("ops/incidents", reliability.IncidentViewSet, basename="ops-incident")
router.register("ops/weather", reliability.WeatherViewSet, basename="ops-weather")
router.register("ops/command", reliability.CommandViewSet, basename="ops-command")
from apps.workspace.powers_api import PowersViewSet  # noqa: E402

router.register("ops/powers", PowersViewSet, basename="ops-powers")
from apps.workspace import company_api  # noqa: E402

router.register("company", company_api.IntranetViewSet, basename="company")
router.register("approvals", company_api.ApprovalsViewSet, basename="approvals")
router.register("ops/brief", reliability.BriefViewSet, basename="ops-brief")
router.register("ops/chief", reliability.ChiefInboxViewSet, basename="ops-chief")
router.register("counters", rides.CounterViewSet, basename="counter")
router.register("ops/fuel", pricing.FuelViewSet, basename="ops-fuel")
router.register("ops/backups", reliability.BackupViewSet, basename="ops-backup")
router.register("announcements", announcements.AnnouncementViewSet, basename="announcement")
router.register("ops/compliance", compliance.ComplianceViewSet, basename="ops-compliance")
router.register("safety/guardian", rides.GuardianViewSet, basename="guardian")
router.register("ops/lost-found", rides.LostFoundOpsViewSet, basename="ops-lost-found")
router.register("riders", riders.RiderViewSet, basename="rider")
router.register("driver/biz", fleet.DriverBusinessViewSet, basename="driver-biz")
router.register("driver", drivers.DriverAppViewSet, basename="driver-self")
router.register("drivers", drivers.DriverViewSet, basename="driver")
router.register("ops/loans", drivers.LoanViewSet, basename="ops-loan")
router.register("ops/speed", drivers.SpeedViewSet, basename="ops-speed")
router.register("wallet", payments.WalletViewSet, basename="wallet")
router.register("payments", payments.PaymentViewSet, basename="payment")
router.register("payouts", payments.PayoutViewSet, basename="payout")
router.register("support/tickets", support.TicketViewSet, basename="ticket")
router.register("safety/incidents", support.IncidentViewSet, basename="incident")
router.register("safety/recordings", support.RecordingViewSet, basename="safety-recording")
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
    path("2fa/", accounts.TwoFactorView.as_view(), name="two-factor"),
    path("2fa/enable/", accounts.TwoFactorEnableView.as_view(), name="two-factor-enable"),
    path("2fa/disable/", accounts.TwoFactorDisableView.as_view(), name="two-factor-disable"),
    path("2fa/verify/", accounts.TwoFactorVerifyView.as_view(), name="two-factor-verify"),
]

analytics_urls = [
    path("overview/", analytics.OverviewView.as_view(), name="analytics-overview"),
    path("timeseries/", analytics.TimeSeriesView.as_view(), name="analytics-timeseries"),
    path("breakdown/", analytics.BreakdownView.as_view(), name="analytics-breakdown"),
    path("trips.csv", analytics.TripExportView.as_view(), name="analytics-trips-csv"),
    path("warehouse/", analytics.WarehouseInsightsView.as_view(), name="analytics-warehouse"),
    path("pnl/", analytics.PnlView.as_view(), name="analytics-pnl"),
]

urlpatterns = [
    path("auth/", include(auth_urls)),
    path("analytics/", include(analytics_urls)),
    path("fares/estimate/", pricing.FareEstimateView.as_view(), name="fare-estimate"),
    path("fares/packages/", rides.PackageQuoteView.as_view(), name="fare-packages"),
    path("fares/nearby-drivers/", rides.NearbyDriversView.as_view(), name="nearby-drivers"),
    path("track/<str:token>/", rides.SharedTripView.as_view(), name="shared-trip"),
    path("safe/<str:token>/", rides.SafeShareView.as_view(), name="safe-share"),
    path("status/", reliability.StatusPageView.as_view(), name="status-page"),
    path("status/banner/", reliability.StatusBannerView.as_view(), name="status-banner"),
    path("places/", geo.PlaceSearchView.as_view(), name="places"),
    path("grievance-officer/", trust.GrievanceOfficerView.as_view(), name="grievance-officer"),
    path("public/company/", company_api.PublicCompanyView.as_view(), name="public-company"),
    path(
        "public/company/jobs/<int:job_id>/", company_api.PublicJobView.as_view(), name="public-job"
    ),
    path("public/company/contact/", company_api.PublicContactView.as_view(), name="public-contact"),
    path("ops/live/", rides.LiveOpsView.as_view(), name="ops-live"),
    path("ops/dispatch/sweep/", rides.DispatchSweepView.as_view(), name="dispatch-sweep"),
    path("ledger/", payments.LedgerView.as_view(), name="ledger"),
    path("gst/returns/", payments.GstReturnView.as_view(), name="gst-returns"),
    path("gst/e-invoice/<int:trip_id>/", payments.EInvoiceView.as_view(), name="gst-e-invoice"),
    path("push/subscription/", PushSubscriptionView.as_view(), name="push-subscription"),
    path("webhooks/echo/", reliability.WebhookEchoView.as_view(), name="webhook-echo"),
    path(
        "payments/razorpay/webhook/",
        payments.RazorpayWebhookView.as_view(),
        name="razorpay-webhook",
    ),
    path("", include(router.urls)),
]
