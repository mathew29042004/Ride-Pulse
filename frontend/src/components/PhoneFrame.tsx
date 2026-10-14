import { clsx } from "clsx";
import { BatteryFull, Monitor, Signal, Smartphone, Wifi } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink } from "react-router";

import { NotificationBell } from "@/components/NotificationBell";
import { type AppTab, AppTabs } from "@/layouts/AppTabs";
import { useLayout } from "@/lib/layout";
import { t } from "@/lib/i18n";

import { Logo, LogoMark } from "./Logo";

function StatusBar() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-[900] flex h-11 items-center justify-between px-7 text-[13px] font-semibold text-fg">
      <span>{now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: false })}</span>
      <span className="flex items-center gap-1.5">
        <Signal className="size-3.5" />
        <Wifi className="size-3.5" />
        <BatteryFull className="size-4" />
      </span>
    </div>
  );
}

interface FrameProps {
  children: ReactNode;
  aside?: ReactNode;
  /** The app's main sections (bottom tabs on a phone, header links on desktop). */
  tabs?: AppTab[];
  /** Hide the tabs (full-screen flows like booking or a live trip). */
  hideTabs?: boolean;
  /** A map screen: full-bleed on desktop. Other screens get a centred, readable column. */
  mapScreen?: boolean;
  title?: string;
}

/**
 * The shell of the rider and driver apps. On a phone the app fills the screen; on a laptop it
 * defaults to a desktop layout (full-screen map with a side panel, tabs in a header), and can
 * switch to a device frame to show the mobile design.
 */
export function PhoneFrame(props: FrameProps) {
  const { mode } = useLayout();
  return mode === "desktop" ? <DesktopFrame {...props} /> : <MobileFrame {...props} />;
}

function MobileFrame({ children, aside, tabs, hideTabs }: FrameProps) {
  const { setMode } = useLayout();
  return (
    <div data-layout="phone" className="min-h-full bg-canvas md:flex md:items-center md:justify-center md:gap-14 md:bg-[radial-gradient(ellipse_at_top_left,rgb(16_185_129/0.18),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgb(14_165_233/0.12),transparent_50%)] md:p-6">
      {aside && (
        <aside className="hidden max-w-sm lg:block">
          {aside}
          <button onClick={() => setMode("desktop")} className="mt-6 flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm font-semibold text-fg hover:bg-surface-2">
            <Monitor className="size-4" /> Switch to the desktop layout
          </button>
        </aside>
      )}
      {/* Always offer the way back to the big-map website layout on laptop-sized screens. */}
      <button
        onClick={() => setMode("desktop")}
        className="fixed top-4 right-4 z-[1000] hidden items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-ink-fg shadow-lg md:flex"
      >
        <Monitor className="size-4" /> Website view
      </button>
      <div className="relative h-dvh w-full md:h-[min(860px,calc(100dvh-48px))] md:w-[400px] md:shrink-0 md:rounded-[52px] md:border-[12px] md:border-[#0b0f19] md:bg-[#0b0f19] md:shadow-[0_40px_80px_-20px_rgb(15_23_42/0.45)]">
        <div id="phone-screen" className="relative flex h-full flex-col overflow-hidden bg-surface md:rounded-[40px]">
          <div className="hidden md:block">
            <StatusBar />
            <div className="absolute top-2.5 left-1/2 z-[950] h-7 w-28 -translate-x-1/2 rounded-full bg-[#0b0f19]" />
          </div>
          <div className="relative flex min-h-0 flex-1 flex-col md:pt-11">{children}</div>
          {tabs && !hideTabs && <AppTabs tabs={tabs} />}
        </div>
      </div>
    </div>
  );
}

function DesktopFrame({ children, tabs, mapScreen, title }: FrameProps) {
  const { setMode } = useLayout();
  return (
    <div data-layout="desktop" className="flex h-dvh flex-col bg-canvas">
      <header className="relative z-[700] flex h-14 shrink-0 items-center gap-6 border-b border-line bg-surface px-5">
        <div className="flex items-center gap-2">
          <Logo />
          {title && <span className="rounded-full bg-surface-3 px-2.5 py-0.5 text-xs font-semibold text-muted">{title}</span>}
        </div>
        {tabs && (
          <nav className="flex items-center gap-1">
            {tabs.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx("flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-semibold transition", isActive ? "bg-ink text-ink-fg" : "text-muted hover:bg-surface-3 hover:text-fg")
                }
              >
                <Icon className="size-4" /> {t(label)}
              </NavLink>
            ))}
          </nav>
        )}
        <div className="ml-auto flex items-center gap-2">
          {tabs && <NotificationBell />}
          <button onClick={() => setMode("phone")} className="flex items-center gap-2 rounded-full border border-line px-3.5 py-2 text-sm font-semibold hover:bg-surface-2" title="See the mobile app design">
            <Smartphone className="size-4" /> Phone view
          </button>
        </div>
      </header>
      <div id="phone-screen" className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {mapScreen ? (
          <div className="relative flex min-h-0 flex-1 flex-col">{children}</div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="relative mx-auto flex min-h-full w-full max-w-2xl flex-col bg-surface shadow-sm md:my-6 md:min-h-[calc(100%-48px)] md:rounded-3xl">{children}</div>
          </div>
        )}
      </div>
    </div>
  );
}

export function FrameAside({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <LogoMark size={44} />
        <div>
          <div className="text-xs font-semibold tracking-widest text-brand uppercase">Ride Pulse</div>
          <div className="text-2xl font-bold tracking-tight">{title}</div>
        </div>
      </div>
      <div className="space-y-4 text-sm leading-relaxed text-muted">{children}</div>
    </div>
  );
}
