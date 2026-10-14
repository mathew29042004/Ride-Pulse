import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router";

import { t } from "@/lib/i18n";

export type AppTab = { to: string; label: string; icon: LucideIcon; end?: boolean };

export function AppTabs({ tabs }: { tabs: AppTab[] }) {
  return (
    <nav className="relative z-[600] grid shrink-0 border-t border-line bg-surface pb-[max(env(safe-area-inset-bottom),6px)]" style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}>
      {tabs.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            clsx("flex flex-col items-center gap-0.5 pt-2.5 pb-1 text-[11px] font-medium transition", isActive ? "text-fg" : "text-muted hover:text-fg")
          }
        >
          {({ isActive }) => (
            <>
              <Icon className={clsx("size-[22px]", isActive && "stroke-[2.4]")} />
              {t(label)}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
