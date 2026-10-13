/** "Now" or a pickup time up to a week ahead, in 15-minute steps (20+ minutes from now). */

import { clsx } from "clsx";
import { useMemo } from "react";

const MIN_LEAD_MS = 20 * 60_000;
const STEP_MS = 15 * 60_000;

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function dayLabel(day: Date, today: Date): string {
  const diff = Math.round((startOfDay(day).getTime() - today.getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return day.toLocaleDateString("en-IN", { weekday: "short", day: "numeric" });
}

export function earliestSlot(now = Date.now()): Date {
  return new Date(Math.ceil((now + MIN_LEAD_MS) / STEP_MS) * STEP_MS);
}

export function formatWhen(at: Date): string {
  const today = startOfDay(new Date());
  return `${dayLabel(at, today)}, ${at.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`;
}

export function SchedulePicker({ value, onChange }: { value: Date | null; onChange: (at: Date | null) => void }) {
  const today = startOfDay(new Date());
  const earliest = earliestSlot();
  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => new Date(today.getTime() + i * 86_400_000)).filter((d) => d.getTime() + 86_400_000 > earliest.getTime()),
    [today.getTime()], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const selectedDay = value ? startOfDay(value) : null;
  const slots = useMemo(() => {
    if (!selectedDay) return [];
    const out: Date[] = [];
    for (let t = Math.max(selectedDay.getTime(), earliest.getTime()); t < selectedDay.getTime() + 86_400_000; t += STEP_MS) out.push(new Date(t));
    return out;
  }, [selectedDay?.getTime(), earliest.getTime()]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickDay = (day: Date) => {
    // Keep the same time of day when switching days, if it's still in the future.
    const at = value ? new Date(day.getTime() + (value.getTime() - startOfDay(value).getTime())) : earliest;
    onChange(at < earliest ? earliest : at.getTime() < day.getTime() ? new Date(Math.max(day.getTime(), earliest.getTime())) : at);
  };

  return (
    <div className="space-y-2.5">
      <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
        <button onClick={() => onChange(null)} className={clsx("shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold", !value ? "border-fg bg-ink text-ink-fg" : "border-line")}>
          Now
        </button>
        {days.map((day) => {
          const active = selectedDay?.getTime() === day.getTime();
          return (
            <button key={day.getTime()} onClick={() => pickDay(day)} className={clsx("shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold", active ? "border-fg bg-ink text-ink-fg" : "border-line")}>
              {dayLabel(day, today)}
            </button>
          );
        })}
      </div>
      {value && (
        <select
          value={value.getTime()}
          onChange={(e) => onChange(new Date(Number(e.target.value)))}
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm font-semibold"
          aria-label="Pickup time"
        >
          {slots.map((slot) => (
            <option key={slot.getTime()} value={slot.getTime()}>
              {slot.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
