/** Ops → Roster: the support desk's week (morning, evening, night) against what the ticket
 * history says is needed, plus leave requests and approvals. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CalendarDays, ChevronLeft, ChevronRight, Wand2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Input, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface Week {
  state: string;
  states: string[];
  week_start: string;
  days: { day: string; slots: { slot: string; label: string; needed: number; people: { id: number; name: string; covering_for: string | null }[] }[] }[];
}
interface Leave {
  id: number;
  name: string;
  kind_label: string;
  starts_on: string;
  ends_on: string;
  days: number;
  reason: string;
  status: string;
  status_label: string;
  note: string;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
const iso = (d: Date) => d.toISOString().slice(0, 10);
const monday = (d = new Date()) => {
  const x = new Date(d);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return iso(x);
};
const shiftWeek = (w: string, n: number) => {
  const d = new Date(w);
  d.setDate(d.getDate() + 7 * n);
  return iso(d);
};

export default function OpsRoster() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [state, setState] = useState<string | null>(null);
  const [week, setWeek] = useState(monday());
  const roster = useQuery({ queryKey: ["roster", state, week], queryFn: () => api.get<Week>(`work/roster/?week=${week}${state ? `&state=${encodeURIComponent(state)}` : ""}`) });
  const leave = useQuery({ queryKey: ["roster", "leave"], queryFn: () => api.get<{ mine: Leave[]; to_decide: Leave[] }>("work/roster/leave/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["roster"] });
  const generate = useMutation({
    mutationFn: (replace: boolean) => api.post<{ shifts: number; gaps: unknown[] }>("work/roster/generate/", { state: roster.data?.state, week_start: week, replace }),
    onSuccess: (r) => {
      toast.success(`${r.shifts} shifts rostered${r.gaps.length ? `, ${r.gaps.length} short` : ""}`);
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const [form, setForm] = useState({ kind: "CASUAL", starts_on: iso(new Date()), ends_on: iso(new Date()), reason: "" });
  const ask = useMutation({
    mutationFn: () => api.post("work/roster/leave/", form),
    onSuccess: () => {
      toast.success("Leave requested: your manager has been told");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post<{ covered: unknown[]; gaps: unknown[] }>(`work/roster/leave/${id}/decide/`, { approve }),
    onSuccess: (r) => {
      toast.success(r.gaps.length ? `Approved, but ${r.gaps.length} shifts need cover` : `Done${r.covered.length ? `: ${r.covered.length} shifts covered` : ""}`);
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const w = roster.data;
  const empty = w?.days.every((d) => d.slots.every((s) => !s.people.length));
  return (
    <>
      <PageHeader title="Roster" subtitle="Support shifts by state. Needs come from the last 4 weeks of tickets (busiest hour of each shift, 3 tickets an hour per agent, at least 2 agents by day and 1 at night). The roster respects leave, at most 6 shifts a week and 11 hours' rest between shifts." />
      <div className="flex flex-wrap items-center gap-2">
        <select value={w?.state ?? ""} onChange={(e) => setState(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="State">
          {(w?.states ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <Button size="sm" variant="outline" icon={<ChevronLeft className="size-4" />} onClick={() => setWeek(shiftWeek(week, -1))} aria-label="Previous week" />
        <span className="flex items-center gap-1 text-sm font-semibold">
          <CalendarDays className="size-4" /> Week of {new Date(week).toLocaleDateString([], { day: "numeric", month: "short" })}
        </span>
        <Button size="sm" variant="outline" icon={<ChevronRight className="size-4" />} onClick={() => setWeek(shiftWeek(week, 1))} aria-label="Next week" />
        {can("team.view") && (
          <Button size="sm" className="ml-auto" icon={<Wand2 className="size-4" />} loading={generate.isPending} onClick={() => generate.mutate(!empty && window.confirm("Replace this week's roster?"))}>
            {empty ? "Generate roster" : "Regenerate"}
          </Button>
        )}
      </div>
      <Card className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr>
              <th className="p-2 text-left text-xs text-muted">Shift</th>
              {(w?.days ?? []).map((d) => (
                <th key={d.day} className="p-2 text-left text-xs text-muted">
                  {new Date(d.day).toLocaleDateString([], { weekday: "short", day: "numeric" })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {["MORNING", "EVENING", "NIGHT"].map((slot, i) => (
              <tr key={slot} className="border-t border-line align-top">
                <td className="p-2 text-xs font-semibold">{w?.days[0]?.slots[i]?.label}</td>
                {(w?.days ?? []).map((d) => {
                  const s = d.slots[i];
                  const short = s.people.length < s.needed;
                  return (
                    <td key={d.day} className={clsx("p-2", short && s.people.length > 0 && "bg-danger/5")}>
                      <div className={clsx("mb-1 text-[11px]", short ? "font-semibold text-danger" : "text-muted")}>
                        {s.people.length}/{s.needed}
                      </div>
                      {s.people.map((p) => (
                        <div key={p.id} className="truncate text-xs">
                          {p.name}
                          {p.covering_for && <span className="text-muted"> (for {p.covering_for.split(" ")[0]})</span>}
                        </div>
                      ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {empty && <p className="p-4 text-sm text-muted">No roster yet for this week.</p>}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <CardHeader title="My leave" />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} className="rounded-xl border border-line bg-surface px-2 py-2 text-sm" aria-label="Kind">
              <option value="CASUAL">Casual</option>
              <option value="SICK">Sick</option>
              <option value="EARNED">Earned</option>
            </select>
            <Input type="date" value={form.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} aria-label="From" />
            <Input type="date" value={form.ends_on} onChange={(e) => setForm({ ...form, ends_on: e.target.value })} aria-label="To" />
            <Button loading={ask.isPending} onClick={() => ask.mutate()}>
              Request
            </Button>
          </div>
          <Input className="mt-2" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Reason (optional)" />
          <div className="mt-3 divide-y divide-line text-sm">
            {(leave.data?.mine ?? []).map((l) => (
              <div key={l.id} className="flex justify-between py-1.5">
                <span>
                  {l.kind_label} · {l.starts_on} – {l.ends_on} ({l.days} d)
                  {l.note && <span className="block text-xs text-muted">{l.note}</span>}
                </span>
                <Badge tone={l.status === "APPROVED" ? "brand" : l.status === "PENDING" ? "warning" : "neutral"}>{l.status_label}</Badge>
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-4">
          <CardHeader title={`To approve (${leave.data?.to_decide.length ?? 0})`} subtitle="Approving takes them off their shifts and finds cover." />
          {(leave.data?.to_decide ?? []).map((l) => (
            <div key={l.id} className="flex items-center gap-2 border-t border-line py-2 text-sm first:border-0">
              <span className="flex-1">
                <b>{l.name}</b> · {l.kind_label}, {l.starts_on} – {l.ends_on} ({l.days} d)
                {l.reason && <span className="block text-xs text-muted">{l.reason}</span>}
              </span>
              <Button size="sm" onClick={() => decide.mutate({ id: l.id, approve: true })}>
                Approve
              </Button>
              <Button size="sm" variant="ghost" onClick={() => decide.mutate({ id: l.id, approve: false })}>
                Decline
              </Button>
            </div>
          ))}
          {leave.data?.to_decide.length === 0 && <p className="text-sm text-muted">Nothing waiting.</p>}
        </Card>
      </div>
    </>
  );
}
