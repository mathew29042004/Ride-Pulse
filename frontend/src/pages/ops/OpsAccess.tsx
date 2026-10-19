/** Ops → Access: managers confirm their team's access each quarter; admins start reviews,
 * offboard leavers (signed out everywhere, work handed over) and check new joiners. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Field, Input, Modal, PageHeader, Select, Stat } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";

interface Item {
  id: number;
  subject_id: number;
  name: string;
  title: string;
  role: string;
  capabilities: number;
  last_login: string | null;
  dormant: boolean;
  decision: string;
  decision_label: string;
  new_role: string;
  note: string;
}
interface Data {
  review: { name: string; due_on: string; total: number; done: number; pct: number; dormant: number } | null;
  mine: Item[];
  roles: string[];
  admin: boolean;
  joiners?: { user_id: number; name: string; title: string; joined_on: string; checks: Record<string, boolean>; done: boolean }[];
  leavers?: { name: string; reason: string; last_day: string; steps: [string, string][]; by: string | null }[];
}

const label = (role: string) => role.replaceAll("_", " ").toLowerCase();

export default function OpsAccess() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["access"], queryFn: () => api.get<Data>("work/access/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["access"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const start = useMutation({ mutationFn: () => api.post("work/access/start/"), onSuccess: () => { toast.success("Review started. Managers have been told."); refresh(); }, onError: fail });
  const [deciding, setDeciding] = useState<{ item: Item; decision: "CHANGE" | "REMOVE" } | null>(null);
  const [newRole, setNewRole] = useState("");
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (v: { id: number; decision: string; new_role?: string; note?: string }) => api.post(`work/access/${v.id}/decide/`, v),
    onSuccess: () => { setDeciding(null); setNote(""); setNewRole(""); refresh(); },
    onError: fail,
  });
  const [leaving, setLeaving] = useState(false);
  const [leaver, setLeaver] = useState("");
  const [reason, setReason] = useState("");
  const offboard = useMutation({
    mutationFn: () => api.post<{ name: string; steps: [string, string][] }>("work/access/offboard/", { user_id: Number(leaver), reason }),
    onSuccess: (r) => { toast.success(`${r.name} offboarded: ${r.steps.length} steps done.`); setLeaving(false); setReason(""); refresh(); },
    onError: fail,
  });
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Access"
        subtitle="Every quarter each manager confirms their team's access. Leavers are signed out everywhere and their work handed over. No sign-in for 45 days is flagged as dormant."
        actions={d?.admin && (
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => setLeaving(true)}>Offboard someone</Button>
            <Button size="sm" loading={start.isPending} onClick={() => start.mutate()}>Start this quarter's review</Button>
          </div>
        )}
      />
      {d?.review && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Card className="p-3"><Stat label={`Review ${d.review.name}`} value={`${d.review.pct}%`} sub={`${d.review.done} of ${d.review.total} done`} /></Card>
          <Card className="p-3"><Stat label="Due" value={d.review.due_on} /></Card>
          <Card className="p-3"><Stat label="Dormant accounts" value={d.review.dormant} /></Card>
          <Card className="p-3"><Stat label="Mine to review" value={d.mine.filter((i) => i.decision === "PENDING").length} /></Card>
        </div>
      )}
      <Card className="mb-4 p-4">
        <CardHeader title="My team's access" />
        {d && !d.mine.length && <p className="text-sm text-muted">Nothing to review right now.</p>}
        <div className="space-y-2">
          {d?.mine.map((i) => (
            <div key={i.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-2 p-2 text-sm">
              <span>
                <b>{i.name}</b> · {i.title} · {label(i.role)} ({i.capabilities} permissions)
                {i.dormant && <Badge tone="warning" className="ml-1">dormant</Badge>}
                <span className="block text-xs text-muted">Last sign-in {i.last_login ? dateTime(i.last_login) : "never"}</span>
              </span>
              {i.decision === "PENDING" ? (
                <span className="flex gap-1">
                  <Button size="sm" onClick={() => decide.mutate({ id: i.id, decision: "KEEP" })}>Keep</Button>
                  <Button size="sm" variant="secondary" onClick={() => setDeciding({ item: i, decision: "CHANGE" })}>Change role</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDeciding({ item: i, decision: "REMOVE" })}>Remove</Button>
                </span>
              ) : (
                <Badge tone={i.decision === "REMOVE" ? "danger" : "brand"}>{i.decision_label}{i.new_role ? `: ${label(i.new_role)}` : ""}</Badge>
              )}
            </div>
          ))}
        </div>
      </Card>
      {d?.admin && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4">
            <CardHeader title="Joiners (last 30 days)" />
            {!d.joiners?.length && <p className="text-sm text-muted">No new joiners.</p>}
            {d.joiners?.map((j) => (
              <div key={j.user_id} className="mb-2 text-sm">
                <b>{j.name}</b> · {j.title} · joined {j.joined_on} {j.done && <Badge tone="brand">ready</Badge>}
                <div className="flex flex-wrap gap-2 text-xs">
                  {Object.entries(j.checks).map(([k, ok]) => <span key={k} className={ok ? "text-brand" : "text-danger"}>{ok ? "✓" : "✗"} {k}</span>)}
                </div>
              </div>
            ))}
          </Card>
          <Card className="p-4">
            <CardHeader title="Recent leavers" />
            {!d.leavers?.length && <p className="text-sm text-muted">Nobody has left.</p>}
            {d.leavers?.map((l, n) => (
              <div key={n} className="mb-2 text-sm">
                <b>{l.name}</b> · last day {l.last_day} · {l.reason}
                <div className="text-xs text-muted">{l.steps.map(([s, x]) => `${s}${x ? ` (${x})` : ""}`).join(" · ")}</div>
              </div>
            ))}
          </Card>
        </div>
      )}
      <Modal open={!!deciding} onClose={() => setDeciding(null)} title={deciding?.decision === "CHANGE" ? `Change ${deciding.item.name}'s role` : `Remove ${deciding?.item.name ?? ""}'s access`}>
        {deciding?.decision === "CHANGE" && (
          <Field label="New role">
            <Select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              <option value="">Choose…</option>
              {d?.roles.filter((r) => r !== deciding.item.role).map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </Select>
          </Field>
        )}
        <Field label={deciding?.decision === "REMOVE" ? "Why? (they're offboarded at once)" : "Note (optional)"} className="mt-2">
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
        </Field>
        <Button className="mt-3" block variant={deciding?.decision === "REMOVE" ? "danger" : "brand"}
          disabled={deciding?.decision === "CHANGE" ? !newRole : note.trim().length < 5}
          loading={decide.isPending}
          onClick={() => deciding && decide.mutate({ id: deciding.item.id, decision: deciding.decision, new_role: newRole, note })}>
          Confirm
        </Button>
      </Modal>
      <Modal open={leaving} onClose={() => setLeaving(false)} title="Offboard a leaver">
        <Field label="Employee user ID"><Input value={leaver} onChange={(e) => setLeaver(e.target.value.replace(/\D/g, ""))} /></Field>
        <Field label="Reason" className="mt-2"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Resigned, last day 31 Oct" /></Field>
        <Button className="mt-3" block variant="danger" disabled={!leaver || reason.trim().length < 5} loading={offboard.isPending} onClick={() => offboard.mutate()}>Offboard now</Button>
      </Modal>
    </>
  );
}
