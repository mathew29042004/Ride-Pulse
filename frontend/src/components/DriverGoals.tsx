/** Driver daily goals ("5 trips today: ₹75 bonus") and going-home mode. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Home, Target } from "lucide-react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { Driver } from "@/lib/types";

export interface GoalProgress {
  date: string;
  completed_today: number;
  tiers: { trips: number; bonus: string; reached: boolean }[];
  earned_today: string;
}

export function useGoals() {
  return useQuery({ queryKey: ["driver", "goals"], queryFn: () => api.get<GoalProgress>("driver/goals/"), refetchInterval: 30_000 });
}

/** "3/5 trips · ₹75 bonus" (the next goal), for the map header. */
export function GoalChip() {
  const goals = useGoals().data;
  if (!goals) return null;
  const next = goals.tiers.find((t) => !t.reached);
  return (
    <div className="mt-0.5 flex items-center gap-1 text-[11px] font-semibold text-brand-strong">
      <Target className="size-3" />
      {next ? `${goals.completed_today}/${next.trips} trips · ₹${Number(next.bonus)} bonus` : `All goals done · ${inr(goals.earned_today)} earned`}
    </div>
  );
}

/** The Earnings page card: each tier with a progress bar. */
export function GoalsCard() {
  const goals = useGoals().data;
  if (!goals) return null;
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <Target className="size-4 text-brand" /> Today's goals
        </div>
        <div className="text-sm text-muted">{goals.completed_today} trips done</div>
      </div>
      <div className="mt-3 space-y-3">
        {goals.tiers.map((tier) => {
          const pct = Math.min(100, (goals.completed_today / tier.trips) * 100);
          return (
            <div key={tier.trips}>
              <div className="flex justify-between text-sm">
                <span>{tier.trips} trips</span>
                <span className={clsx("font-semibold", tier.reached && "text-brand-strong")}>
                  {tier.reached ? "✓ " : ""}+₹{Number(tier.bonus)}
                </span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-muted">Bonuses are paid straight into your wallet when you reach each goal. They reset at midnight.</p>
    </div>
  );
}

/** "Going home" switch: only trips towards home, for an hour, twice a day. */
export function GoingHomeButton({ driver }: { driver: Driver }) {
  const qc = useQueryClient();
  const now = useNow(30_000);
  const toggle = useMutation({
    mutationFn: (on: boolean) => api.post<Driver>("driver/going-home/", { on }),
    onSuccess: (updated) => {
      qc.setQueryData(["driver", "me"], updated);
      toast.success(updated.going_home_until ? `Going home: only trips towards ${updated.home_address || "home"}` : "Going-home mode is off");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't change going-home mode."),
  });
  if (driver.home_lat === null) return null;
  const until = driver.going_home_until ? new Date(driver.going_home_until).getTime() : 0;
  const active = until > now;
  const minutesLeft = Math.max(0, Math.ceil((until - now) / 60_000));
  return (
    <button
      onClick={() => toggle.mutate(!active)}
      disabled={toggle.isPending || (!active && driver.going_home_uses_left === 0)}
      className={clsx("flex items-center gap-1.5 rounded-full px-3 py-2 text-xs font-bold shadow-lg disabled:opacity-50", active ? "bg-violet-600 text-white" : "bg-surface")}
      aria-pressed={active}
      title={active ? "Only trips towards home" : `${driver.going_home_uses_left} uses left today`}
    >
      <Home className="size-4" /> {active ? `Going home · ${minutesLeft} min` : "Going home"}
    </button>
  );
}
