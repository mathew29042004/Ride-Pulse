import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Activity, BadgeIndianRupee, CloudSun, BellRing, BookOpen, CalendarDays, Clock, Wallet, Building2, FlaskConical, KeyRound, Landmark, Scale, CarTaxiFront, ChartNoAxesCombined, ClipboardList, Database, FileCheck, FileText, Gauge, Headset, LayoutDashboard, LogOut, Map, Menu, Moon, Megaphone, MessagesSquare, Network, PackageSearch, PieChart, Plane, Receipt, Route, ScrollText, ShieldAlert, ShieldCheck, ShieldX, Smile, Siren, CloudRain, DatabaseBackup, Sun, Sunrise, Tag, Target, TrendingUp, Users, Wrench, X } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { OfflineBanner } from "@/components/OfflineBanner";
import { Logo } from "@/components/Logo";
import { NotificationBell } from "@/components/NotificationBell";
import { Avatar, Badge, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import type { City, Overview } from "@/lib/types";

interface OpsContextValue {
  city: string; // "" means all cities
  setCity: (slug: string) => void;
  cities: City[];
  cityInfo: City | undefined;
}

const OpsContext = createContext<OpsContextValue | null>(null);

export function useOps(): OpsContextValue {
  const ctx = useContext(OpsContext);
  if (!ctx) throw new Error("useOps must be used inside OpsLayout");
  return ctx;
}

const NAV = [
  {
    group: "Operate",
    items: [
      { to: "/ops", label: "Dashboard", icon: LayoutDashboard, end: true, cap: "trips.view" },
      { to: "/ops/live", label: "Live map", icon: Map, cap: "trips.view" },
      { to: "/ops/trips", label: "Trips", icon: Route, cap: "trips.view" },
      { to: "/ops/drivers", label: "Drivers", icon: CarTaxiFront, cap: "drivers.view" },
      { to: "/ops/verification", label: "Verification", icon: FileCheck, cap: "drivers.verify" },
      { to: "/ops/riders", label: "Riders", icon: Users, cap: "riders.view" },
    ],
  },
  {
    group: "Marketplace",
    items: [
      { to: "/ops/pricing", label: "Pricing & surge", icon: Gauge, cap: "pricing.view" },
      { to: "/ops/promos", label: "Promotions", icon: Tag, cap: "promos.manage" },
      { to: "/ops/finance", label: "Payments & payouts", icon: BadgeIndianRupee, cap: "payments.view" },
      { to: "/ops/analytics", label: "Analytics", icon: ChartNoAxesCombined, cap: "reports.view" },
      { to: "/ops/insights", label: "Data insights", icon: Database, cap: "reports.view" },
    ],
  },
  {
    group: "Fleet & partners",
    items: [
      { to: "/ops/fleet-owners", label: "Fleet owners", icon: Building2, cap: "fleet.manage" },
      { to: "/ops/quests", label: "Quests", icon: Target, cap: "fleet.manage" },
      { to: "/ops/upkeep", label: "Vehicle health", icon: Wrench, cap: "fleet.manage" },
      { to: "/ops/tours", label: "Tours", icon: Landmark, cap: "tours.manage" },
      { to: "/ops/airports", label: "Airports & EVs", icon: Plane, cap: "fleet.manage" },
      { to: "/ops/tds", label: "TDS", icon: Receipt, cap: "payments.view" },
      { to: "/ops/pnl", label: "City P&L", icon: PieChart, cap: "payments.view" },
      { to: "/ops/gst", label: "GST", icon: FileText, cap: "payments.view" },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { to: "/ops/briefing", label: "Morning briefing", icon: Sunrise, cap: "reports.view" },
      { to: "/ops/alerts", label: "Alerts", icon: BellRing, cap: "reports.view" },
      { to: "/ops/demand", label: "Demand forecast", icon: TrendingUp, cap: "reports.view" },
      { to: "/ops/outlook", label: "Weather & events", icon: CloudSun, cap: "reports.view" },
      { to: "/ops/fraud", label: "Fraud review", icon: ShieldX, cap: "fraud.review" },
      { to: "/ops/nps", label: "NPS", icon: Smile, cap: "reports.view" },
      { to: "/ops/models", label: "Models & experiments", icon: FlaskConical, cap: "reports.view" },
    ],
  },
  {
    group: "Care",
    items: [
      { to: "/ops/support", label: "Support", icon: Headset, cap: "support.view" },
      { to: "/ops/safety", label: "Safety (SOS)", icon: ShieldAlert, cap: "safety.manage", badge: "sos" as const },
      { to: "/ops/lost-found", label: "Lost & found", icon: PackageSearch, cap: "support.view" },
      { to: "/ops/trust", label: "Trust & privacy", icon: ShieldCheck, cap: "privacy.manage" },
      { to: "/ops/compliance", label: "Compliance", icon: Scale, cap: "drivers.view" },
      { to: "/ops/audit", label: "Audit trail", icon: ScrollText, cap: "audit.view" },
      { to: "/ops/platform", label: "Platform health", icon: Activity, cap: "audit.view" },
      { to: "/ops/incidents", label: "Incidents", icon: Siren, cap: "trips.view" },
      { to: "/ops/loans", label: "Vehicle loans", icon: Landmark, cap: "payouts.manage" },
      { to: "/ops/weather", label: "Monsoon mode", icon: CloudRain, cap: "pricing.view" },
      { to: "/ops/backups", label: "Backups", icon: DatabaseBackup, cap: "audit.view" },
      { to: "/ops/work", label: "Work", icon: ClipboardList, cap: "work.use" },
      { to: "/ops/chat", label: "Team chat", icon: MessagesSquare, cap: "work.use" },
      { to: "/ops/roster", label: "Roster & leave", icon: CalendarDays, cap: "work.use" },
      { to: "/ops/attendance", label: "Attendance", icon: Clock, cap: "work.use" },
      { to: "/ops/payslips", label: "My payslips", icon: FileText, cap: "work.use" },
      { to: "/ops/expenses", label: "Expenses", icon: Receipt, cap: "work.use" },
      { to: "/ops/payroll", label: "Payroll", icon: Wallet, cap: "payroll.manage" },
      { to: "/ops/announcements", label: "Announcements", icon: Megaphone, cap: "announce" },
      { to: "/ops/help", label: "Handbook", icon: BookOpen, cap: "work.use" },
      { to: "/ops/security", label: "Security", icon: KeyRound, cap: "work.use" },
      { to: "/ops/team", label: "Team", icon: Network, cap: "team.view" },
    ],
  },
];

/** Admins and managers without two-step sign-in get a reminder on every ops page. */
function TwoStepReminder() {
  const status = useQuery({ queryKey: ["2fa"], queryFn: () => api.get<{ enabled: boolean; required: boolean }>("auth/2fa/"), staleTime: 300_000 });
  if (!status.data || status.data.enabled || !status.data.required) return null;
  return (
    <NavLink to="/ops/security" className="mb-3 flex items-center gap-2 rounded-xl bg-amber-500/15 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
      <KeyRound className="size-4" /> Two-step sign-in is required for your role. Set it up in two minutes →
    </NavLink>
  );
}

export default function OpsLayout() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [city, setCityState] = useState(() => localStorage.getItem("rp.ops.city") ?? "");
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/") });
  const live = useQuery({
    queryKey: ["ops", "overview-badge"],
    queryFn: () => api.get<Overview>("analytics/overview/?days=1"),
    refetchInterval: 15_000,
    enabled: can("reports.view"),
  });

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const setCity = (slug: string) => {
    setCityState(slug);
    localStorage.setItem("rp.ops.city", slug);
  };
  const openSos = live.data?.live.open_sos ?? 0;

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center justify-between px-5">
        <Logo light />
        <button className="text-white/60 lg:hidden" onClick={() => setMenuOpen(false)} aria-label="Close menu">
          <X className="size-5" />
        </button>
      </div>
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {NAV.map((section) => {
          const items = section.items.filter((item) => can(item.cap));
          if (!items.length) return null;
          return (
            <div key={section.group}>
              <div className="px-3 pb-2 text-[11px] font-semibold tracking-widest text-white/35 uppercase">{section.group}</div>
              <div className="space-y-0.5">
                {items.map(({ to, label, icon: Icon, ...rest }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={"end" in rest && rest.end}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
                        isActive ? "bg-white/10 text-white" : "text-white/60 hover:bg-white/5 hover:text-white",
                      )
                    }
                  >
                    <Icon className="size-[18px]" />
                    <span className="flex-1">{label}</span>
                    {"badge" in rest && openSos > 0 && <span className="rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">{openSos}</span>}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>
      <div className="border-t border-white/10 p-4">
        <div className="flex items-center gap-3">
          <Avatar name={`${user?.first_name} ${user?.last_name}`} size={36} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-white">
              {user?.first_name} {user?.last_name}
            </div>
            <div className="truncate text-xs text-white/50">{user?.role_label ?? user?.role.replaceAll("_", " ").toLowerCase()}</div>
          </div>
          <button
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
            className="rounded-lg p-2 text-white/50 hover:bg-white/10 hover:text-white"
            aria-label="Log out"
            title="Log out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <OpsContext.Provider value={{ city, setCity, cities: cities.data ?? [], cityInfo: cities.data?.find((c) => c.slug === city) }}>
      <div className="flex h-full">
        <aside className="hidden w-64 shrink-0 bg-[#080b12] lg:block">{sidebar}</aside>
        {menuOpen && (
          <div className="fixed inset-0 z-[1100] lg:hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setMenuOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 bg-[#080b12]">{sidebar}</aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface px-4 lg:px-8">
            <button className="rounded-lg p-2 hover:bg-surface-3 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu">
              <Menu className="size-5" />
            </button>
            <Select value={city} onChange={(e) => setCity(e.target.value)} className="!w-44 !py-2" aria-label="City">
              <option value="">All cities</option>
              {(cities.data ?? []).map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.name}
                </option>
              ))}
            </Select>
            {live.data && (
              <div className="hidden items-center gap-2 text-xs md:flex">
                <Badge tone="brand">
                  <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" /> {live.data.live.drivers_online + live.data.live.drivers_on_trip} drivers live
                </Badge>
                <Badge tone="info">{live.data.live.active_trips} active trips</Badge>
                {openSos > 0 && <Badge tone="danger">{openSos} open SOS</Badge>}
              </div>
            )}
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className="flex size-10 items-center justify-center rounded-full hover:bg-surface-3"
                aria-label="Toggle dark mode"
              >
                {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
              </button>
              <NotificationBell />
            </div>
          </header>
          <main className="min-h-0 flex-1 overflow-y-auto">
            <div className={clsx(pathname === "/ops/live" ? "h-full" : "mx-auto max-w-7xl px-4 py-6 lg:px-8")}>
              <OfflineBanner />
              <TwoStepReminder />
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </OpsContext.Provider>
  );
}
