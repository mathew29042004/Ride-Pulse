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
const RiderHome = lazy(() => import("./pages/rider/RiderHome"));
const RiderBook = lazy(() => import("./pages/rider/RiderBook"));
const RiderPackages = lazy(() => import("./pages/rider/RiderPackages"));
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
      { path: "trips/:id", element: lazyPage(<RiderTrip />) },
      { path: "activity", element: lazyPage(<RiderActivity />) },
      { path: "wallet", element: lazyPage(<RiderWallet />) },
      { path: "account", element: lazyPage(<RiderAccount />) },
      { path: "support", element: lazyPage(<SupportList base="/ride" />) },
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
      { path: "support", element: lazyPage(<SupportList base="/drive" />) },
      { path: "support/:id", element: lazyPage(<TicketThread base="/drive" />) },
    ],
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
      { path: "work/tasks/:id", element: lazyPage(<WorkTaskPage />) },
      { path: "work/meetings/:id", element: lazyPage(<WorkMeetingPage />) },
      { path: "insights", element: lazyPage(<OpsInsights />) },
    ],
  },
  { path: "*", element: <NotFound /> },
]);
