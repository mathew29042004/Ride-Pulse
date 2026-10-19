/** Driver daily goals ("5 trips today: ₹75 bonus") and going-home mode. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Home, Target } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { Driver } from "@/lib/types";
import { t } from "@/lib/i18n";

export interface GoalProgress {
  date: string;
  completed_today: number;
  tiers: { trips: number; bonus: string; reached: boolean }[];
  earned_today: string;
  earnings_today: string;
  earnings_goal: number;
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
      {next ? t("{done}/{trips} trips · ₹{bonus} bonus", { done: goals.completed_today, trips: next.trips, bonus: Number(next.bonus) }) : t("All goals done · {amount} earned", { amount: inr(goals.earned_today) })}
    </div>
  );
}

/** Today's earnings against the driver's own goal, as a ring; tap to change the goal. */
export function EarningsGoal() {
  const qc = useQueryClient();
  const goals = useGoals().data;
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<GoalProgress>("driver/earnings-goal/", { amount: Number(amount) || 0 }),
    onSuccess: (g) => {
      qc.setQueryData(["driver", "goals"], g);
      setEditing(false);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't save the goal.")),
  });
  if (!goals) return null;
  const earned = Number(goals.earnings_today);
  const goal = goals.earnings_goal;
  const pct = goal ? Math.min(1, earned / goal) : 0;
  const r = 30;
  const c = 2 * Math.PI * r;
  return (
    <div className="mt-4 flex items-center gap-4 rounded-2xl border border-line p-4">
      <svg viewBox="0 0 72 72" className="size-20 shrink-0 -rotate-90" aria-hidden>
        <circle cx="36" cy="36" r={r} fill="none" stroke="var(--color-surface-3)" strokeWidth="8" />
        <circle cx="36" cy="36" r={r} fill="none" stroke="var(--color-brand)" strokeWidth="8" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} className="transition-all duration-700" />
      </svg>
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{t("Today's earnings goal")}</div>
        {goal ? (
          <div className="text-sm text-muted">{pct >= 1 ? t("Goal reached! 🎉") : t("{earned} of {goal}", { earned: inr(earned, { whole: true }), goal: inr(goal, { whole: true }) })}</div>
        ) : (
          <div className="text-sm text-muted">{t("Set a daily earnings goal to track your progress.")}</div>
        )}
        {editing ? (
          <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <input type="number" min={0} max={20000} step={100} value={amount} onChange={(e) => setAmount(e.target.value)} className="input !w-28 !py-1.5" aria-label={t("Today's earnings goal")} autoFocus />
            <button type="submit" className="rounded-full bg-brand px-3 text-xs font-semibold text-on-brand">{t("Save")}</button>
          </form>
        ) : (
          <button className="mt-1 text-xs font-semibold text-brand" onClick={() => { setAmount(String(goal || 1500)); setEditing(true); }}>{t("Set a goal")}</button>
        )}
      </div>
    </div>
  );
}

/** The Earnings page card: each tier with a progress bar. */
export function GoalsCard() {
  const goals = useGoals().data;
  if (!goals) return null;
  return (
    <>
    <EarningsGoal />
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          <Target className="size-4 text-brand" /> {t("Today's goals")}
        </div>
        <div className="text-sm text-muted">{goals.completed_today} trips done</div>
      </div>
      <div className="mt-3 space-y-3">
        {goals.tiers.map((tier) => {
          const pct = Math.min(100, (goals.completed_today / tier.trips) * 100);
          return (
            <div key={tier.trips}>
              <div className="flex justify-between text-sm">
                <span>{t("{n} trips", { n: tier.trips })}</span>
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
      <p className="mt-3 text-xs text-muted">{t("Bonuses are paid straight into your wallet when you reach each goal. They reset at midnight.")}</p>
    </div>
    </>
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
      toast.success(updated.going_home_until ? t("Going home: only trips towards {place}", { place: updated.home_address || t("home") }) : t("Going-home mode is off"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't change going-home mode.")),
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
      title={active ? t("Only trips towards home") : t("{n} uses left today", { n: driver.going_home_uses_left })}
    >
      <Home className="size-4" /> {active ? t("Going home · {m} min", { m: minutesLeft }) : t("Going home")}
    </button>
  );
}
