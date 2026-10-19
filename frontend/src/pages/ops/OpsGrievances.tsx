/** Ops → Grievances: the grievance officer's queue. Acknowledge within 48 hours, resolve in
 * writing within 15 days; late ones escalate to the appellate officer by themselves. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Modal, PageHeader, Segmented, Stat, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";

interface Grievance {
  id: number;
  number: string;
  category_label: string;
  subject: string;
  description: string;
  status: string;
  status_label: string;
  created_at: string;
  ack_due: string;
  resolve_due: string;
  resolution: string;
  escalation_reason: string;
  raised_by: string;
  who: string;
  trip_number: string | null;
  handled_by: string | null;
  appellate_officer: string | null;
  satisfied: boolean | null;
  overdue: boolean;
}
interface Data {
  officer: { name: string; email: string; phone: string };
  compliance: { received: number; open: number; ack_on_time_pct: number | null; resolved_on_time_pct: number | null; escalated: number };
  grievances: Grievance[];
}

export default function OpsGrievances() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["grievances", filter], queryFn: () => api.get<Data>(`ops/trust/grievances/${filter ? `?status=${filter}` : ""}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["grievances"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const ack = useMutation({ mutationFn: (id: number) => api.post(`ops/trust/grievances/${id}/acknowledge/`), onSuccess: refresh, onError: fail });
  const [resolving, setResolving] = useState<Grievance | null>(null);
  const [text, setText] = useState("");
  const resolve = useMutation({
    mutationFn: () => api.post(`ops/trust/grievances/${resolving!.id}/resolve/`, { resolution: text }),
    onSuccess: () => { setResolving(null); setText(""); refresh(); },
    onError: fail,
  });
  const c = q.data?.compliance;
  return (
    <>
      <PageHeader title="Grievances" subtitle={`Grievance officer ${q.data?.officer.name ?? ""} · acknowledge within 48 hours, resolve in writing within 15 days. Late ones go to the appellate officer automatically.`} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Card className="p-3"><Stat label="Received (90 days)" value={c?.received ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Open" value={c?.open ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Acknowledged on time" value={c?.ack_on_time_pct != null ? `${c.ack_on_time_pct}%` : "—"} /></Card>
        <Card className="p-3"><Stat label="Resolved on time" value={c?.resolved_on_time_pct != null ? `${c.resolved_on_time_pct}%` : "—"} /></Card>
        <Card className="p-3"><Stat label="Escalated" value={c?.escalated ?? "—"} /></Card>
      </div>
      <Segmented className="mb-3" value={filter} onChange={setFilter} options={[{ value: "", label: "All" }, { value: "RECEIVED", label: "New" }, { value: "ACKNOWLEDGED", label: "In progress" }, { value: "ESCALATED", label: "Escalated" }, { value: "RESOLVED", label: "Resolved" }]} />
      <div className="space-y-2">
        {q.data?.grievances.map((g) => (
          <Card key={g.id} className={clsx("p-3 text-sm", g.overdue && "border-danger")}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{g.number} · {g.subject}</span>
              <Badge tone={g.status === "RESOLVED" || g.status === "CLOSED" ? "brand" : g.status === "ESCALATED" ? "danger" : "warning"}>{g.status_label}</Badge>
              {g.overdue && <Badge tone="danger">Overdue</Badge>}
              <span className="text-xs text-muted">{g.who}: {g.raised_by} · {g.category_label}{g.trip_number ? ` · ${g.trip_number}` : ""} · {dateTime(g.created_at)}</span>
            </div>
            <p className="mt-1 text-muted">{g.description}</p>
            <div className="mt-1 text-xs text-muted">
              {g.status === "RECEIVED" ? `Acknowledge by ${dateTime(g.ack_due)}` : ""} {["RECEIVED", "ACKNOWLEDGED", "ESCALATED"].includes(g.status) ? `· resolve by ${dateTime(g.resolve_due)}` : ""}
              {g.handled_by && ` · handled by ${g.handled_by}`}{g.appellate_officer && ` · appellate officer ${g.appellate_officer}`}
            </div>
            {g.escalation_reason && <div className="mt-1 text-xs text-danger">Escalated: {g.escalation_reason}</div>}
            {g.resolution && <div className="mt-2 rounded-xl bg-surface-2 p-2 text-xs">{g.resolution}{g.satisfied === true && " · ✓ satisfied"}</div>}
            {["RECEIVED", "ACKNOWLEDGED", "ESCALATED"].includes(g.status) && (
              <div className="mt-2 flex gap-2">
                {g.status === "RECEIVED" && <Button size="sm" variant="secondary" loading={ack.isPending} onClick={() => ack.mutate(g.id)}>Acknowledge</Button>}
                <Button size="sm" onClick={() => setResolving(g)}>Write resolution</Button>
              </div>
            )}
          </Card>
        ))}
        {q.data && !q.data.grievances.length && <p className="text-sm text-muted">Nothing here.</p>}
      </div>
      <Modal open={!!resolving} onClose={() => setResolving(null)} title={`Resolve ${resolving?.number ?? ""}`}>
        <p className="mb-2 text-sm text-muted">What you found and what was done. The person gets this in writing.</p>
        <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} aria-label="Resolution" />
        <Button className="mt-3" block disabled={text.trim().length < 20} loading={resolve.isPending} onClick={() => resolve.mutate()}>Send resolution</Button>
      </Modal>
    </>
  );
}
