/** Ops → Appraisals: write your self-review, rate your team against six months of evidence,
 * and (admins) start and close the half-yearly cycle, which applies the pay rises. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, PageHeader, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";

interface Appraisal {
  id: number;
  employee: string;
  manager: string;
  status: string;
  status_label: string;
  self_review: string;
  self_rating: number | null;
  evidence: Record<string, unknown> & { attendance?: Record<string, number | null> };
  concerns: string[];
  rating: number | null;
  rating_label: string;
  manager_comment: string;
  raise_percent: string | null;
  new_gross: string | null;
}
interface Data {
  cycle: { name: string; closed: boolean } | null;
  mine: Appraisal[];
  team: Appraisal[];
  raises: Record<string, string>;
  admin: boolean;
  progress?: Record<string, number>;
}

function Stars({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Rating">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} role="radio" aria-checked={value === n} onClick={() => onChange(n)} className={clsx("size-8 rounded-lg text-sm font-bold", value >= n ? "bg-ink text-ink-fg" : "bg-surface-2")}>{n}</button>
      ))}
    </div>
  );
}

function Evidence({ e }: { e: Appraisal["evidence"] }) {
  const att = e.attendance ?? {};
  const items: [string, unknown][] = [
    ["Tasks done", e.done_tasks], ["Overdue", e.overdue_tasks], ["On time", e.on_time_rate != null ? `${e.on_time_rate}%` : null],
    ["Tickets", e.tickets_resolved], ["SLA met", e.sla_met_rate != null ? `${e.sla_met_rate}%` : null], ["CSAT", e.csat_percent != null ? `${e.csat_percent}%` : null],
    ["Present", att.present], ["Late", att.late], ["Absent", att.absent], ["Leave", att.on_leave],
  ];
  return (
    <div className="grid grid-cols-5 gap-1 text-center text-xs">
      {items.map(([k, v]) => <div key={k} className="rounded-lg bg-surface-2 p-1"><div className="text-muted">{k}</div><div className="font-semibold">{v == null ? "—" : String(v)}</div></div>)}
    </div>
  );
}

export default function OpsAppraisals() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["appraisals"], queryFn: () => api.get<Data>("work/appraisals/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["appraisals"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const [text, setText] = useState<Record<number, string>>({});
  const [stars, setStars] = useState<Record<number, number>>({});
  const self = useMutation({ mutationFn: (id: number) => api.post(`work/appraisals/${id}/self/`, { text: text[id] ?? "", rating: stars[id] ?? 3 }), onSuccess: refresh, onError: fail });
  const rate = useMutation({ mutationFn: (id: number) => api.post(`work/appraisals/${id}/rate/`, { comment: text[id] ?? "", rating: stars[id] ?? 3 }), onSuccess: refresh, onError: fail });
  const start = useMutation({ mutationFn: () => api.post("work/appraisals/start/"), onSuccess: refresh, onError: fail });
  const close = useMutation({ mutationFn: () => api.post<{ raises: number; effective: string }>("work/appraisals/close/"), onSuccess: (r) => { toast.success(`${r.raises} raises from ${r.effective}`); refresh(); }, onError: fail });
  const d = q.data;
  const raises = d ? Object.entries(d.raises).map(([r, p]) => `${r}★ ${p}%`).join(" · ") : "";
  return (
    <>
      <PageHeader
        title={`Appraisals${d?.cycle ? ` · ${d.cycle.name}` : ""}`}
        subtitle={`Self-review, then your manager rates you against six months of evidence. Raises: ${raises}.`}
        actions={d?.admin && (
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" loading={start.isPending} onClick={() => start.mutate()}>Start cycle</Button>
            {d.cycle && !d.cycle.closed && <Button size="sm" loading={close.isPending} onClick={() => close.mutate()}>Close and apply raises</Button>}
          </div>
        )}
      />
      {d?.progress && <p className="mb-3 text-sm text-muted">{Object.entries(d.progress).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(" · ")}</p>}
      {d?.mine.map((a) => (
        <Card key={a.id} className="mb-4 space-y-2 p-4">
          <CardHeader title="My appraisal" subtitle={`Manager: ${a.manager}`} />
          <Badge tone="neutral">{a.status_label}</Badge>
          {a.status === "SELF" ? (
            <>
              <Textarea rows={4} value={text[a.id] ?? ""} onChange={(e) => setText({ ...text, [a.id]: e.target.value })} placeholder="What went well, what you'd improve" aria-label="Self-review" />
              <Stars value={stars[a.id] ?? 3} onChange={(n) => setStars({ ...stars, [a.id]: n })} />
              <Button loading={self.isPending} onClick={() => self.mutate(a.id)}>Send to my manager</Button>
            </>
          ) : (
            <p className="text-sm">{a.self_review}</p>
          )}
          {a.rating && <p className="text-sm"><b>{a.rating}★ {a.rating_label}</b> · {a.manager_comment}{a.new_gross && ` · new salary ${inr(a.new_gross)}`}</p>}
        </Card>
      ))}
      {d && d.team.length > 0 && (
        <Card className="p-4">
          <CardHeader title="My team" />
          <div className="space-y-3">
            {d.team.map((a) => (
              <div key={a.id} className="rounded-xl border border-line p-3 text-sm">
                <div className="flex items-center gap-2 font-semibold">{a.employee} <Badge tone="neutral">{a.status_label}</Badge>{a.self_rating && <span className="text-xs text-muted">self {a.self_rating}★</span>}</div>
                {a.self_review && <p className="mt-1 text-muted">{a.self_review}</p>}
                {a.status !== "SELF" && <div className="mt-2"><Evidence e={a.evidence} /></div>}
                {a.concerns.length > 0 && <p className="mt-1 text-xs text-amber-600">Evidence: {a.concerns.join(", ")}</p>}
                {a.status === "MANAGER" && (
                  <div className="mt-2 space-y-2">
                    <Stars value={stars[a.id] ?? 3} onChange={(n) => setStars({ ...stars, [a.id]: n })} />
                    <Textarea rows={3} value={text[a.id] ?? ""} onChange={(e) => setText({ ...text, [a.id]: e.target.value })} placeholder="Your comment (they'll see it)" aria-label="Manager comment" />
                    <Button size="sm" loading={rate.isPending} onClick={() => rate.mutate(a.id)}>Save rating</Button>
                  </div>
                )}
                {a.rating && <p className="mt-1"><b>{a.rating}★</b> · {a.manager_comment} · raise {a.raise_percent}%</p>}
              </div>
            ))}
          </div>
        </Card>
      )}
      {d && !d.cycle && <p className="text-sm text-muted">No appraisal cycle yet.</p>}
    </>
  );
}
