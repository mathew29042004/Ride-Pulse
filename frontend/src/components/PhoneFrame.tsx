import { BatteryFull, Signal, Wifi } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { LogoMark } from "./Logo";

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

/**
 * On a phone the app fills the screen. On a laptop it renders inside a device frame next to a
 * short explainer, so the rider and driver apps demo like real mobile apps.
 */
export function PhoneFrame({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="min-h-full bg-canvas md:flex md:items-center md:justify-center md:gap-14 md:bg-[radial-gradient(ellipse_at_top_left,rgb(16_185_129/0.18),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgb(14_165_233/0.12),transparent_50%)] md:p-6">
      {aside && <aside className="hidden max-w-sm lg:block">{aside}</aside>}
      <div className="relative h-dvh w-full md:h-[min(860px,calc(100dvh-48px))] md:w-[400px] md:shrink-0 md:rounded-[52px] md:border-[12px] md:border-[#0b0f19] md:bg-[#0b0f19] md:shadow-[0_40px_80px_-20px_rgb(15_23_42/0.45)]">
        <div id="phone-screen" className="relative flex h-full flex-col overflow-hidden bg-surface md:rounded-[40px]">
          <div className="hidden md:block">
            <StatusBar />
            <div className="absolute top-2.5 left-1/2 z-[950] h-7 w-28 -translate-x-1/2 rounded-full bg-[#0b0f19]" />
          </div>
          {children}
        </div>
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
