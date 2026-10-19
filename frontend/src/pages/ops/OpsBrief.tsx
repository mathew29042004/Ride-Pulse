/** Ops → Brief the chief (the chief of staff, and administrators): send the chief an update, a
 * briefing (drafted from live data in one click) or an escalation; escalate a watchtower alert;
 * ask the chief to decide, optionally proposing an order that goes into force when approved.
 * The chief's replies and decisions arrive live. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Crown, NotebookPen, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Segmented, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useSocket } from "@/lib/ws";

type Kind = "UPDATE" | "BRIEFING" | "ESCALATION";
interface Desk {
  updates: { id: number; kind: Kind; kind_label: string; title: string; body: string; sent_at: string; read: boolean; reply: string }[];
  decisions: { id: number; title: string; order: string; asked_at: string; status: string; status_label: string; decided_by: string | null; note: string }[];
  draft: { title: string; body: string };
  alerts: { id: number; level: string; title: string; detail: string; raised_at: string }[];
  cities: { id: number; name: string }[];
  chiefs: string[];
}

export default function OpsBrief() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "brief"], queryFn: () => api.get<Desk>("ops/brief/"), refetchInterval: 30_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "brief"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  useSocket("/ws/chat/", (msg) => {
    if (msg.event === "chief_reply") {
      const u = msg.data as { title: string; reply: string };
      toast.success(`The chief replied: ${u.title}`, { description: u.reply, duration: 12_000 });
      refresh();
    } else if (msg.event === "decision_made") {
      const x = msg.data as { title: string; status_label: string; note: string };
      toast.success(`${x.status_label}: ${x.title}`, { description: x.note || undefined, duration: 12_000 });
      refresh();
    }
  });

  const [kind, setKind] = useState<Kind>("UPDATE");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const send = useMutation({
    mutationFn: () => api.post("ops/brief/", { kind, title, body }),
    onSuccess: () => {
      toast.success("Sent. The chief sees it now.");
      setTitle("");
      setBody("");
      refresh();
    },
    onError: fail,
  });
  const escalate = useMutation({
    mutationFn: (alert: number) => api.post("ops/brief/escalate/", { alert }),
    onSuccess: () => {
      toast.success("Escalated to the chief.");
      refresh();
    },
    onError: fail,
  });

  const [askTitle, setAskTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [orderKind, setOrderKind] = useState("");
  const [city, setCity] = useState<number | null>(null);
  const [vehicle, setVehicle] = useState("BIKE");
  const [hours, setHours] = useState(2);
  const ask = useMutation({
    mutationFn: () =>
      api.post("ops/brief/ask/", {
        title: askTitle,
        detail,
        order: orderKind ? { kind: orderKind, city, vehicle_code: vehicle, hours, reason: askTitle } : {},
      }),
    onSuccess: () => {
      toast.success("Sent to the chief for a decision.");
      setAskTitle("");
      setDetail("");
      setOrderKind("");
      refresh();
    },
    onError: fail,
  });

  const d = q.data;
  return (
    <>
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><NotebookPen className="size-6 text-amber-300" /> Brief the chief</span>}
        subtitle={d?.chiefs.length ? `Everything here reaches ${d.chiefs.join(" and ")} live.` : "Everything here reaches the chief live."}
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-4">
          <Card className="space-y-3 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">Send an update</h3>
              <Button
                size="sm"
                variant="outline"
                icon={<Sparkles className="size-3.5" />}
                disabled={!d}
                onClick={() => {
                  if (!d) return;
                  setKind("BRIEFING");
                  setTitle(d.draft.title);
                  setBody(d.draft.body);
                }}
              >
                Draft a briefing from live data
              </Button>
            </div>
            <Segmented value={kind} onChange={setKind} options={[{ value: "UPDATE", label: "Update" }, { value: "BRIEFING", label: "Briefing" }, { value: "ESCALATION", label: "Escalation" }]} />
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} placeholder="Title" aria-label="Title" />
            <Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} placeholder="What the chief needs to know" aria-label="Message" className="min-h-36" />
            <Button block variant={kind === "ESCALATION" ? "danger" : "primary"} disabled={title.trim().length < 3} loading={send.isPending} onClick={() => send.mutate()}>
              {kind === "ESCALATION" ? "Escalate now" : "Send to the chief"}
            </Button>
          </Card>

          <Card className="space-y-3 p-4">
            <h3 className="flex items-center gap-2 font-semibold"><Crown className="size-4 text-amber-500" /> Ask the chief to decide</h3>
            <Input value={askTitle} onChange={(e) => setAskTitle(e.target.value)} maxLength={160} placeholder="e.g. Pause bike taxis in Kochi tonight?" aria-label="Question" />
            <Textarea value={detail} onChange={(e) => setDetail(e.target.value)} maxLength={4000} placeholder="Why, and what you recommend" aria-label="Detail" />
            <Field label="Propose an order (optional)" hint="If the chief approves, it goes into force at once.">
              <Select value={orderKind} onChange={(e) => setOrderKind(e.target.value)}>
                <option value="">No order, just a decision</option>
                <option value="PAUSE_BOOKINGS">Pause all bookings</option>
                <option value="PAUSE_VEHICLE">Pause one vehicle type</option>
                <option value="SURGE_OFF">Turn surge off</option>
              </Select>
            </Field>
            {orderKind && (
              <div className="grid grid-cols-2 gap-2">
                <Select value={city ?? ""} onChange={(e) => setCity(Number(e.target.value) || null)} aria-label="City">
                  <option value="">All cities</option>
                  {d?.cities.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
                <Input type="number" min={1} max={72} value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Hours" />
                {orderKind === "PAUSE_VEHICLE" && (
                  <Select value={vehicle} onChange={(e) => setVehicle(e.target.value)} aria-label="Vehicle">
                    <option value="BIKE">Bike taxis</option>
                    <option value="AUTO">Autos</option>
                    <option value="CAR">Cars</option>
                  </Select>
                )}
              </div>
            )}
            <Button block disabled={askTitle.trim().length < 5} loading={ask.isPending} onClick={() => ask.mutate()}>Send for a decision</Button>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><BellRing className="size-4 text-danger" /> Live alerts</span>} subtitle="Escalate one and the chief sees it at once." />
            {d && !d.alerts.length && <EmptyState title="No open alerts" />}
            <div className="max-h-72 divide-y divide-line overflow-y-auto">
              {d?.alerts.map((a) => (
                <div key={a.id} className="flex items-start justify-between gap-3 px-5 py-2.5 text-sm">
                  <div>
                    <div className="font-medium"><Badge tone={a.level === "CRITICAL" ? "danger" : "warning"}>{a.level === "CRITICAL" ? "Critical" : "Warning"}</Badge> {a.title}</div>
                    <div className="text-xs text-muted">{a.detail}</div>
                  </div>
                  <Button size="sm" variant="danger" loading={escalate.isPending} onClick={() => escalate.mutate(a.id)}>Escalate</Button>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Decisions you asked for" />
            {d && !d.decisions.length && <EmptyState title="None yet" />}
            <div className="divide-y divide-line">
              {d?.decisions.map((x) => (
                <div key={x.id} className="px-5 py-2.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{x.title}</span>
                    <Badge tone={x.status === "APPROVED" ? "brand" : x.status === "DECLINED" ? "neutral" : "warning"}>{x.status_label}</Badge>
                  </div>
                  {x.order && <div className="text-xs">Order: {x.order}</div>}
                  <div className="text-xs text-muted">{dateTime(x.asked_at)}{x.decided_by ? ` · ${x.decided_by}` : ""}{x.note ? ` · “${x.note}”` : ""}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="What you've sent" />
            {d && !d.updates.length && <EmptyState title="Nothing sent yet" />}
            <div className="divide-y divide-line">
              {d?.updates.map((u) => (
                <div key={u.id} className="px-5 py-2.5 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge tone={u.kind === "ESCALATION" ? "danger" : u.kind === "BRIEFING" ? "info" : "neutral"}>{u.kind_label}</Badge>
                    <span className="font-medium">{u.title}</span>
                    <span className="ml-auto text-xs text-muted">{u.read ? "Seen" : "Not seen yet"}</span>
                  </div>
                  {u.reply && <div className="mt-1 rounded-lg bg-amber-500/10 px-2 py-1 text-xs"><span className="font-semibold">Chief:</span> {u.reply}</div>}
                  <div className="text-xs text-muted">{dateTime(u.sent_at)}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
