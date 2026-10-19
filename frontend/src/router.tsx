import { lazy, type ReactNode, Suspense } from "react";
import { createBrowserRouter, Navigate, useLocation } from "react-router";

import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import Landing from "./pages/public/Landing";
import Login from "./pages/public/Login";
import ErrorPage from "./pages/public/ErrorPage";
import NotFound from "./pages/public/NotFound";
import Signup from "./pages/public/Signup";
import SwitchAccount from "./pages/public/SwitchAccount";

// Each app is its own chunk: riders never download the operations console.
const RiderLayout = lazy(() => import("./layouts/RiderLayout"));
const TrackTrip = lazy(() => import("./pages/public/TrackTrip"));
const SafeShare = lazy(() => import("./pages/public/SafeShare"));
const StatusPage = lazy(() => import("./pages/public/StatusPage"));
const GrievanceOfficer = lazy(() => import("./pages/public/GrievanceOfficer"));
const OpsGrievances = lazy(() => import("./pages/ops/OpsGrievances"));
const RiderHome = lazy(() => import("./pages/rider/RiderHome"));
const RiderBook = lazy(() => import("./pages/rider/RiderBook"));
const RiderPackages = lazy(() => import("./pages/rider/RiderPackages"));
const RiderTours = lazy(() => import("./pages/rider/RiderTours"));
const RiderTrip = lazy(() => import("./pages/rider/RiderTrip"));
const RiderActivity = lazy(() => import("./pages/rider/RiderActivity"));
const RiderWallet = lazy(() => import("./pages/rider/RiderWallet"));
const RiderAccount = lazy(() => import("./pages/rider/RiderAccount"));
const TicketThread = lazy(() => import("./pages/shared/TicketThread"));
const SupportList = lazy(() => import("./pages/shared/SupportList"));

const DriverLayout = lazy(() => import("./layouts/DriverLayout"));
const DriverHome = lazy(() => import("./pages/driver/DriverHome"));
const DriverEarnings = lazy(() => import("./pages/driver/DriverEarnings"));
const DriverDocuments = lazy(() => import("./pages/driver/DriverDocuments"));
const DriverAccount = lazy(() => import("./pages/driver/DriverAccount"));
const DriverAcademy = lazy(() => import("./pages/driver/DriverAcademy"));
const DriverLoan = lazy(() => import("./pages/driver/DriverLoan"));
const OpsLoans = lazy(() => import("./pages/ops/OpsLoans"));

const OpsLayout = lazy(() => import("./layouts/OpsLayout"));
const OpsDashboard = lazy(() => import("./pages/ops/OpsDashboard"));
const OpsLive = lazy(() => import("./pages/ops/OpsLive"));
const OpsTrips = lazy(() => import("./pages/ops/OpsTrips"));
const OpsTripDetail = lazy(() => import("./pages/ops/OpsTripDetail"));
const OpsDrivers = lazy(() => import("./pages/ops/OpsDrivers"));
const OpsDriverDetail = lazy(() => import("./pages/ops/OpsDriverDetail"));
const OpsVerification = lazy(() => import("./pages/ops/OpsVerification"));
const OpsRiders = lazy(() => import("./pages/ops/OpsRiders"));
const OpsPricing = lazy(() => import("./pages/ops/OpsPricing"));
const OpsPromos = lazy(() => import("./pages/ops/OpsPromos"));
const OpsSupport = lazy(() => import("./pages/ops/OpsSupport"));
const OpsTicket = lazy(() => import("./pages/ops/OpsTicket"));
const OpsSafety = lazy(() => import("./pages/ops/OpsSafety"));
const OpsFinance = lazy(() => import("./pages/ops/OpsFinance"));
const OpsAnalytics = lazy(() => import("./pages/ops/OpsAnalytics"));
const OpsAudit = lazy(() => import("./pages/ops/OpsAudit"));
const OpsTeam = lazy(() => import("./pages/ops/OpsTeam"));
const OpsWork = lazy(() => import("./pages/ops/work/OpsWork"));
const FleetPortal = lazy(() => import("./pages/fleet/FleetPortal"));
const RiderBusiness = lazy(() => import("./pages/rider/RiderBusiness"));
const RiderCommute = lazy(() => import("./pages/rider/RiderCommute"));
const trust = () => import("./pages/shared/Trust");
const PrivacyCentre = lazy(() => trust().then((m) => ({ default: m.PrivacyCentre })));
const HelpCentre = lazy(() => trust().then((m) => ({ default: m.HelpCentre })));
const ClaimsPage = lazy(() => trust().then((m) => ({ default: m.ClaimsPage })));
const AppealsRider = lazy(() => trust().then((m) => ({ default: () => <m.Appeals base="/ride" subjects={m.RIDER_APPEALS} /> })));
const AppealsDriver = lazy(() => trust().then((m) => ({ default: () => <m.Appeals base="/drive" subjects={m.DRIVER_APPEALS} /> })));
const GrievancesRider = lazy(() => trust().then((m) => ({ default: () => <m.Grievances base="/ride" /> })));
const GrievancesDriver = lazy(() => trust().then((m) => ({ default: () => <m.Grievances base="/drive" /> })));
const OpsPlatform = lazy(() => import("./pages/ops/OpsPlatform"));
const OpsModels = lazy(() => import("./pages/ops/OpsModels"));
const OpsTours = lazy(() => import("./pages/ops/OpsTours"));
const OpsLostFound = lazy(() => import("./pages/ops/OpsLostFound"));
const OpsChat = lazy(() => import("./pages/ops/OpsChat"));
const OpsSecurity = lazy(() => import("./pages/ops/OpsSecurity"));
const OpsCompliance = lazy(() => import("./pages/ops/OpsCompliance"));
const OpsRoster = lazy(() => import("./pages/ops/work/OpsRoster"));
const OpsAnnouncements = lazy(() => import("./pages/ops/OpsAnnouncements"));
const OpsIncidents = lazy(() => import("./pages/ops/OpsIncidents"));
const OpsPnl = lazy(() => import("./pages/ops/OpsPnl"));
const OpsGst = lazy(() => import("./pages/ops/OpsGst"));
const OpsNps = lazy(() => import("./pages/ops/OpsNps"));
const OpsWeather = lazy(() => import("./pages/ops/OpsWeather"));
const OpsBackups = lazy(() => import("./pages/ops/OpsBackups"));
const OpsAttendance = lazy(() => import("./pages/ops/OpsAttendance"));
const OpsPayroll = lazy(() => import("./pages/ops/OpsPayroll"));
const OpsPayslips = lazy(() => import("./pages/ops/OpsPayslips"));
const OpsExpenses = lazy(() => import("./pages/ops/OpsExpenses"));
const OpsAccess = lazy(() => import("./pages/ops/OpsAccess"));
const OpsAppraisals = lazy(() => import("./pages/ops/OpsAppraisals"));
const OpsCounter = lazy(() => import("./pages/ops/OpsCounter"));
const OpsFuel = lazy(() => import("./pages/ops/OpsFuel"));
const OpsSpeed = lazy(() => import("./pages/ops/OpsSpeed"));
const OpsTrust = lazy(() => import("./pages/ops/OpsTrust"));
const opsFleet = () => import("./pages/ops/fleet/OpsFleet");
const OpsFleetOwners = lazy(() => opsFleet().then((m) => ({ default: m.OpsFleetOwners })));
const OpsQuests = lazy(() => opsFleet().then((m) => ({ default: m.OpsQuests })));
const OpsUpkeep = lazy(() => opsFleet().then((m) => ({ default: m.OpsUpkeep })));
const OpsAirportsEv = lazy(() => opsFleet().then((m) => ({ default: m.OpsAirportsEv })));
const OpsTds = lazy(() => opsFleet().then((m) => ({ default: m.OpsTds })));
const intel = () => import("./pages/ops/intel/OpsIntel");
const OpsBriefing = lazy(() => intel().then((m) => ({ default: m.OpsBriefing })));
const OpsAlerts = lazy(() => intel().then((m) => ({ default: m.OpsAlerts })));
const OpsDemand = lazy(() => intel().then((m) => ({ default: m.OpsDemand })));
const OpsFraud = lazy(() => intel().then((m) => ({ default: m.OpsFraud })));
const OpsOutlook = lazy(() => intel().then((m) => ({ default: m.OpsOutlook })));
const WorkTaskPage = lazy(() => import("./pages/ops/work/WorkDetail").then((m) => ({ default: m.WorkTaskPage })));
const WorkMeetingPage = lazy(() => import("./pages/ops/work/WorkDetail").then((m) => ({ default: m.WorkMeetingPage })));
const OpsInsights = lazy(() => import("./pages/ops/OpsInsights"));

function FullScreenSpinner() {
  return (
    <div className="flex h-full min-h-[50vh] items-center justify-center">
      <Spinner className="size-7" />
    </div>
  );
}

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<FullScreenSpinner />}>{children}</Suspense>;
}

const STAFF: Role[] = [
  "ADMIN",
  "REGIONAL_MANAGER",
  "OPS_MANAGER",
  "ASSOC_RIDES",
  "ASSOC_SUPPORT",
  "ASSOC_MAINTENANCE",
  "ASSOC_INTERCITY",
  "ASSOC_PARCELS",
  "SUPPORT_LEAD",
  "SUPPORT_AGENT",
  "FLEET_EXECUTIVE",
];

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullScreenSpinner />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (!roles.includes(user.role)) {
    return <SwitchAccount app={`/${location.pathname.split("/")[1]}`} roles={roles} />;
  }
  return <Lazy>{children}</Lazy>;
}

const lazyPage = (element: ReactNode) => <Lazy>{element}</Lazy>;

export const router = createBrowserRouter([
  { path: "/", element: <Landing />, errorElement: <ErrorPage /> },
  { path: "/login", element: <Login />, errorElement: <ErrorPage /> },
  { path: "/signup", element: <Signup kind="rider" />, errorElement: <ErrorPage /> },
  { path: "/signup/driver", element: <Signup kind="driver" />, errorElement: <ErrorPage /> },
  { path: "/track/:token", element: lazyPage(<TrackTrip />), errorElement: <ErrorPage /> },
  { path: "/safe/:token", element: lazyPage(<SafeShare />), errorElement: <ErrorPage /> },
  { path: "/status", element: lazyPage(<StatusPage />), errorElement: <ErrorPage /> },
  { path: "/grievance-officer", element: lazyPage(<GrievanceOfficer />), errorElement: <ErrorPage /> },
  {
    path: "/ride",
    errorElement: <ErrorPage />,
    element: (
      <RequireRole roles={["RIDER"]}>
        <RiderLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: lazyPage(<RiderHome />) },
      { path: "book", element: lazyPage(<RiderBook />) },
      { path: "packages", element: lazyPage(<RiderPackages />) },
      { path: "tours", element: lazyPage(<RiderTours />) },
      { path: "trips/:id", element: lazyPage(<RiderTrip />) },
      { path: "activity", element: lazyPage(<RiderActivity />) },
      { path: "wallet", element: lazyPage(<RiderWallet />) },
      { path: "account", element: lazyPage(<RiderAccount />) },
      { path: "business/:id", element: lazyPage(<RiderBusiness />) },
      { path: "commute", element: lazyPage(<RiderCommute />) },
      { path: "support", element: lazyPage(<SupportList base="/ride" />) },
      { path: "privacy", element: lazyPage(<PrivacyCentre base="/ride" />) },
      { path: "help", element: lazyPage(<HelpCentre base="/ride" />) },
      { path: "help/:slug", element: lazyPage(<HelpCentre base="/ride" />) },
      { path: "claims", element: lazyPage(<ClaimsPage base="/ride" />) },
      { path: "appeals", element: lazyPage(<AppealsRider />) },
      { path: "grievances", element: lazyPage(<GrievancesRider />) },
      { path: "support/:id", element: lazyPage(<TicketThread base="/ride" />) },
    ],
  },
  {
    path: "/drive",
    errorElement: <ErrorPage />,
    element: (
      <RequireRole roles={["DRIVER"]}>
        <DriverLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: lazyPage(<DriverHome />) },
      { path: "earnings", element: lazyPage(<DriverEarnings />) },
      { path: "documents", element: lazyPage(<DriverDocuments />) },
      { path: "account", element: lazyPage(<DriverAccount />) },
      { path: "academy", element: lazyPage(<DriverAcademy />) },
      { path: "loan", element: lazyPage(<DriverLoan />) },
      { path: "support", element: lazyPage(<SupportList base="/drive" />) },
      { path: "privacy", element: lazyPage(<PrivacyCentre base="/drive" />) },
      { path: "help", element: lazyPage(<HelpCentre base="/drive" />) },
      { path: "help/:slug", element: lazyPage(<HelpCentre base="/drive" />) },
      { path: "claims", element: lazyPage(<ClaimsPage base="/drive" />) },
      { path: "appeals", element: lazyPage(<AppealsDriver />) },
      { path: "grievances", element: lazyPage(<GrievancesDriver />) },
      { path: "support/:id", element: lazyPage(<TicketThread base="/drive" />) },
    ],
  },
  {
    path: "/fleet",
    errorElement: <ErrorPage />,
    element: (
      <RequireRole roles={["FLEET_OWNER"]}>
        <FleetPortal />
      </RequireRole>
    ),
  },
  {
    path: "/ops",
    errorElement: <ErrorPage />,
    element: (
      <RequireRole roles={STAFF}>
        <OpsLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: lazyPage(<OpsDashboard />) },
      { path: "live", element: lazyPage(<OpsLive />) },
      { path: "trips", element: lazyPage(<OpsTrips />) },
      { path: "trips/:id", element: lazyPage(<OpsTripDetail />) },
      { path: "drivers", element: lazyPage(<OpsDrivers />) },
      { path: "drivers/:id", element: lazyPage(<OpsDriverDetail />) },
      { path: "verification", element: lazyPage(<OpsVerification />) },
      { path: "riders", element: lazyPage(<OpsRiders />) },
      { path: "pricing", element: lazyPage(<OpsPricing />) },
      { path: "promos", element: lazyPage(<OpsPromos />) },
      { path: "support", element: lazyPage(<OpsSupport />) },
      { path: "support/:id", element: lazyPage(<OpsTicket />) },
      { path: "safety", element: lazyPage(<OpsSafety />) },
      { path: "safety/:id", element: lazyPage(<OpsSafety />) },
      { path: "finance", element: lazyPage(<OpsFinance />) },
      { path: "analytics", element: lazyPage(<OpsAnalytics />) },
      { path: "audit", element: lazyPage(<OpsAudit />) },
      { path: "team", element: lazyPage(<OpsTeam />) },
      { path: "work", element: lazyPage(<OpsWork />) },
      { path: "briefing", element: lazyPage(<OpsBriefing />) },
      { path: "platform", element: lazyPage(<OpsPlatform />) },
      { path: "models", element: lazyPage(<OpsModels />) },
      { path: "tours", element: lazyPage(<OpsTours />) },
      { path: "lost-found", element: lazyPage(<OpsLostFound />) },
      { path: "chat", element: lazyPage(<OpsChat />) },
      { path: "security", element: lazyPage(<OpsSecurity />) },
      { path: "compliance", element: lazyPage(<OpsCompliance />) },
      { path: "roster", element: lazyPage(<OpsRoster />) },
      { path: "attendance", element: lazyPage(<OpsAttendance />) },
      { path: "payroll", element: lazyPage(<OpsPayroll />) },
      { path: "payslips", element: lazyPage(<OpsPayslips />) },
      { path: "expenses", element: lazyPage(<OpsExpenses />) },
      { path: "access", element: lazyPage(<OpsAccess />) },
      { path: "appraisals", element: lazyPage(<OpsAppraisals />) },
      { path: "counter", element: lazyPage(<OpsCounter />) },
      { path: "fuel", element: lazyPage(<OpsFuel />) },
      { path: "speed", element: lazyPage(<OpsSpeed />) },
      { path: "grievances", element: lazyPage(<OpsGrievances />) },
      { path: "announcements", element: lazyPage(<OpsAnnouncements />) },
      { path: "incidents", element: lazyPage(<OpsIncidents />) },
      { path: "weather", element: lazyPage(<OpsWeather />) },
      { path: "backups", element: lazyPage(<OpsBackups />) },
      { path: "loans", element: lazyPage(<OpsLoans />) },
      { path: "pnl", element: lazyPage(<OpsPnl />) },
      { path: "gst", element: lazyPage(<OpsGst />) },
      { path: "nps", element: lazyPage(<OpsNps />) },
      { path: "help", element: lazyPage(<HelpCentre base="/ops" />) },
      { path: "help/:slug", element: lazyPage(<HelpCentre base="/ops" />) },
      { path: "chat/:id", element: lazyPage(<OpsChat />) },
      { path: "trust", element: lazyPage(<OpsTrust />) },
      { path: "fleet-owners", element: lazyPage(<OpsFleetOwners />) },
      { path: "quests", element: lazyPage(<OpsQuests />) },
      { path: "upkeep", element: lazyPage(<OpsUpkeep />) },
      { path: "airports", element: lazyPage(<OpsAirportsEv />) },
      { path: "tds", element: lazyPage(<OpsTds />) },
      { path: "alerts", element: lazyPage(<OpsAlerts />) },
      { path: "demand", element: lazyPage(<OpsDemand />) },
      { path: "fraud", element: lazyPage(<OpsFraud />) },
      { path: "outlook", element: lazyPage(<OpsOutlook />) },
      { path: "work/tasks/:id", element: lazyPage(<WorkTaskPage />) },
      { path: "work/meetings/:id", element: lazyPage(<WorkMeetingPage />) },
      { path: "insights", element: lazyPage(<OpsInsights />) },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
