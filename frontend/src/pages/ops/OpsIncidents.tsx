/** Ops → Incidents: open one when part of the service breaks, post updates (riders and drivers
 * see the public message; /status shows it to anyone), resolve, then write the review. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Siren } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Input, Modal, PageHeader, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";

interface Incident {
  id: number;
  number: string;
  title: string;
  severity: string;
  severity_label: string;
  status: string;
  status_label: string;
  components: string[];
  public_message: string;
  started_at: string;
  resolved_at: string | null;
  minutes: number;
  summary: string;
  root_cause: string;
  reviewed_at: string | null;
  updates: { status_label: string; message: string; at: string; by: string | null }[];
}

const COMPONENTS = [
  ["BOOKING", "Booking"],
  ["PAYMENTS", "Payments"],
  ["MAPS", "Maps & ETAs"],
  ["DRIVER_APP", "Driver app"],
  ["NOTIFICATIONS", "Notifications"],
  ["SUPPORT", "Support"],
] as const;
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

export default function OpsIncidents() {
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["incidents"], queryFn: () => api.get<Incident[]>("ops/incidents/"), refetchInterval: 20_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["incidents"] });
  const [opening, setOpening] = useState(false);
  const [form, setForm] = useState({ title: "", severity: "MAJOR", components: [] as string[], public_message: "" });
  const [reviewing, setReviewing] = useState<Incident | null>(null);
  const [review, setReview] = useState({ summary: "", root_cause: "" });
  const open = useMutation({
    mutationFn: () => api.post("ops/incidents/", form),
    onSuccess: () => {
      toast.success("Incident opened: riders and drivers see the message");
      setOpening(false);
      setForm({ title: "", severity: "MAJOR", components: [], public_message: "" });
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const progress = useMutation({
    mutationFn: ({ id, status, message }: { id: number; status: string; message: string }) => api.post(`ops/incidents/${id}/progress/`, { status, message }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorText(e)),
  });
  const saveReview = useMutation({
    mutationFn: () => api.post(`ops/incidents/${reviewing!.id}/review/`, review),
    onSuccess: () => {
      toast.success("Review saved");
      setReviewing(null);
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const step = (i: Incident, status: string) => {
    const message = window.prompt(`Update for ${i.number}: what changed?`);
    if (message) progress.mutate({ id: i.id, status, message });
  };
  return (
    <>
      <PageHeader
        title="Incidents"
        subtitle="When part of the service breaks: open an incident, keep it updated (riders and drivers see the public message, /status shows it to anyone, #operations gets every update), resolve it, then write a blameless review."
        actions={
          <Button icon={<Siren className="size-4" />} onClick={() => setOpening(true)}>
            Open incident
          </Button>
        }
      />
      <div className="space-y-3">
        {(rows.data ?? []).map((i) => (
          <Card key={i.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{i.title}</span>
              <Badge tone={i.status === "RESOLVED" ? "brand" : "danger"}>{i.status_label}</Badge>
              <Badge tone="neutral">{i.severity_label}</Badge>
              <span className="ml-auto text-xs text-muted">
                {i.number} · {dateTime(i.started_at)} · {i.minutes} min
              </span>
            </div>
            <p className="mt-1 text-sm">{i.public_message}</p>
            <div className="mt-2 space-y-0.5 text-xs text-muted">
              {i.updates.map((u, k) => (
                <div key={k}>
                  <b>{u.status_label}</b> · {dateTime(u.at)} · {u.by}: {u.message}
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {i.status !== "RESOLVED" ? (
                <>
                  {i.status === "INVESTIGATING" && (
                    <Button size="sm" variant="outline" onClick={() => step(i, "IDENTIFIED")}>
                      Cause found
                    </Button>
                  )}
                  {i.status !== "MONITORING" && (
                    <Button size="sm" variant="outline" onClick={() => step(i, "MONITORING")}>
                      Fixed, monitoring
                    </Button>
                  )}
                  <Button size="sm" onClick={() => step(i, "RESOLVED")}>
                    Resolve
                  </Button>
                </>
              ) : i.reviewed_at ? (
                <div className="text-sm">
                  <b>Review:</b> {i.summary} <span className="text-muted">Root cause: {i.root_cause}</span>
                </div>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setReviewing(i)}>
                  Write the review
                </Button>
              )}
            </div>
          </Card>
        ))}
        {rows.data?.length === 0 && <p className="text-sm text-muted">No incidents. All systems operational.</p>}
      </div>

      <Modal open={opening} onClose={() => setOpening(false)} title="Open incident" footer={<Button block variant="danger" loading={open.isPending} onClick={() => open.mutate()}>Open</Button>}>
        <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="What's broken, e.g. Card payments failing" />
        <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="Severity">
          <option value="MINOR">Minor: degraded</option>
          <option value="MAJOR">Major: partly down</option>
          <option value="CRITICAL">Critical: down</option>
        </select>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {COMPONENTS.map(([key, label]) => (
            <button key={key} onClick={() => setForm({ ...form, components: form.components.includes(key) ? form.components.filter((c) => c !== key) : [...form.components, key] })} className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${form.components.includes(key) ? "border-ink bg-ink text-ink-fg" : "border-line"}`}>
              {label}
            </button>
          ))}
        </div>
        <Textarea className="mt-2" rows={2} value={form.public_message} onChange={(e) => setForm({ ...form, public_message: e.target.value })} placeholder="What riders and drivers see, with a workaround, e.g. Card payments are delayed. UPI and cash work." />
      </Modal>

      <Modal open={!!reviewing} onClose={() => setReviewing(null)} title={`Review ${reviewing?.number ?? ""}`} footer={<Button block loading={saveReview.isPending} onClick={() => saveReview.mutate()}>Save review</Button>}>
        <p className="mb-2 text-xs text-muted">Blameless: what happened and why, not who. Add follow-up tasks from the Work page.</p>
        <Textarea rows={3} value={review.summary} onChange={(e) => setReview({ ...review, summary: e.target.value })} placeholder="What happened, for how long, who was affected" />
        <Textarea className="mt-2" rows={2} value={review.root_cause} onChange={(e) => setReview({ ...review, root_cause: e.target.value })} placeholder="Root cause" />
      </Modal>
    </>
  );
}
