import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router";

import { t } from "@/lib/i18n";

export type AppTab = { to: string; label: string; icon: LucideIcon; end?: boolean };

export function AppTabs({ tabs }: { tabs: AppTab[] }) {
  return (
    <nav className="relative z-[600] mx-3 mb-[max(env(safe-area-inset-bottom),10px)] grid shrink-0 rounded-[24px] bg-surface/95 px-1 py-1 shadow-[0_14px_34px_-14px_rgb(49_46_129/0.45)] ring-1 ring-line/60 backdrop-blur" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
      {tabs.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            clsx("flex flex-col items-center gap-0.5 py-1.5 text-[11px] font-semibold transition", isActive ? "text-brand-strong" : "text-muted hover:text-fg")
          }
        >
          {({ isActive }) => (
            <>
              <span className={clsx("flex h-7 w-12 items-center justify-center rounded-full transition", isActive && "bg-[image:var(--gradient-brand)] text-white shadow-[0_6px_14px_-6px_rgb(124_58_237/0.8)]")}>
                <Icon className={clsx("size-[20px]", isActive && "stroke-[2.4]")} />
              </span>
              {t(label)}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
