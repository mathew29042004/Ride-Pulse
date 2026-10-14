import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, CheckCircle2, Lock, Send, UserCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Field, Input, KeyValue, Modal, Spinner, StatusBadge, Textarea, Toggle } from "@/components/ui";
import { SafetyRecordings } from "@/components/TripRecorder";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, inr } from "@/lib/format";
import type { Ticket, Trip } from "@/lib/types";

export default function OpsTicket() {
  const { id } = useParams();
  const { user, can } = useAuth();
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolution, setResolution] = useState("");
  const [refund, setRefund] = useState("0");
  const ticket = useQuery({ queryKey: ["tickets", id], queryFn: () => api.get<Ticket>(`support/tickets/${id}/`), refetchInterval: 10_000 });
  const trip = useQuery({ queryKey: ["trips", String(ticket.data?.trip)], queryFn: () => api.get<Trip>(`trips/${ticket.data!.trip}/`), enabled: !!ticket.data?.trip });
  const refresh = () => qc.invalidateQueries({ queryKey: ["tickets"] });
  const onError = (err: unknown) => toast.error((err as Error).message);
  const reply = useMutation({ mutationFn: () => api.post(`support/tickets/${id}/reply/`, { body, internal }), onSuccess: () => { setBody(""); refresh(); }, onError });
  const assign = useMutation({ mutationFn: () => api.post(`support/tickets/${id}/assign/`, { agent: user!.id }), onSuccess: () => { toast.success("Assigned to you"); refresh(); }, onError });
  const resolve = useMutation({
    mutationFn: () => api.post(`support/tickets/${id}/resolve/`, { resolution, refund_amount: refund || "0" }),
    onSuccess: () => {
      toast.success(Number(refund) > 0 ? `Resolved with a ${inr(refund)} refund` : "Ticket resolved");
      setResolveOpen(false);
      refresh();
    },
    onError,
  });

  const t = ticket.data;
  if (!t) return <Spinner className="mx-auto mt-20 size-7" />;
  const open = !["RESOLVED", "CLOSED"].includes(t.status);

  return (
    <>
      <Link to="/ops/support" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" /> Support
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t.subject}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            {t.ticket_number} <StatusBadge status={t.priority} /> <StatusBadge status={t.status === "IN_PROGRESS" ? "IN_PROGRESS_TICKET" : t.status} label={t.status.replace(/_/g, " ").toLowerCase()} />
            {t.escalated && <Badge tone="danger">SLA breached</Badge>}
          </div>
        </div>
        {open && can("support.manage") && (
          <div className="flex gap-2">
            <Button variant="outline" icon={<UserCheck className="size-4" />} onClick={() => assign.mutate()} loading={assign.isPending}>
              Assign to me
            </Button>
            <Button variant="brand" icon={<CheckCircle2 className="size-4" />} onClick={() => setResolveOpen(true)}>
              Resolve
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Card className="flex flex-col">
          <div className="max-h-[60vh] flex-1 space-y-3 overflow-y-auto p-5">
            <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-surface-3 px-4 py-3 text-sm">
              <div className="mb-1 text-xs font-semibold">{t.raised_by}</div>
              {t.description}
              <div className="mt-1 text-[11px] text-muted">{dateTime(t.created_at)}</div>
            </div>
            {t.messages.map((m) => (
              <div
                key={m.id}
                className={clsx(
                  "max-w-[80%] rounded-2xl px-4 py-3 text-sm",
                  m.is_internal ? "ml-auto border border-dashed border-amber-400 bg-amber-50 dark:bg-amber-400/10" : m.author_is_staff ? "ml-auto rounded-tr-sm bg-ink text-ink-fg" : "rounded-tl-sm bg-surface-3",
                )}
              >
                <div className="mb-1 flex items-center gap-1 text-xs font-semibold">
                  {m.is_internal && <Lock className="size-3" />} {m.author} {m.is_internal && "· internal note"}
                </div>
                {m.body}
                <div className="mt-1 text-[11px] opacity-60">{dateTime(m.created_at)}</div>
              </div>
            ))}
            {t.resolution && (
              <div className="rounded-2xl border border-brand/40 bg-brand-soft p-3 text-sm">
                <b>Resolution:</b> {t.resolution} {Number(t.refund_amount) > 0 && `· refunded ${inr(t.refund_amount)}`}
              </div>
            )}
          </div>
          {open && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (body.trim()) reply.mutate();
              }}
              className="flex items-center gap-2 border-t border-line p-3"
            >
              <label className="flex items-center gap-2 text-xs font-medium whitespace-nowrap text-muted">
                <Toggle checked={internal} onChange={setInternal} label="Internal note" /> Internal
              </label>
              <Input value={body} onChange={(e) => setBody(e.target.value)} placeholder={internal ? "Note for the team (not visible to the customer)" : "Reply to the customer"} />
              <Button type="submit" icon={<Send className="size-4" />} loading={reply.isPending}>
                Send
              </Button>
            </form>
          )}
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Details" />
            <div className="px-5 py-2">
              <KeyValue label="Category">{t.category.replace(/_/g, " ").toLowerCase()}</KeyValue>
              <KeyValue label="Assignee">{t.assigned_to ?? "Unassigned"}</KeyValue>
              <KeyValue label="SLA due">{dateTime(t.sla_due_at)}</KeyValue>
              <KeyValue label="Opened">{dateTime(t.created_at)}</KeyValue>
            </div>
          </Card>
          {t.category === "SAFETY" && <SafetyRecordings ticketId={t.id} />}
          {trip.data && (
            <Card>
              <CardHeader title="Trip" action={<Link className="text-xs font-semibold text-muted hover:text-fg" to={`/ops/trips/${trip.data.id}`}>Open →</Link>} />
              <div className="px-5 py-2">
                <KeyValue label="Trip">{trip.data.trip_number}</KeyValue>
                <KeyValue label="Status">
                  <StatusBadge status={trip.data.status} />
                </KeyValue>
                <KeyValue label="Fare">{inr(trip.data.fare_total ?? trip.data.estimated_fare)}</KeyValue>
                <KeyValue label="Pricing">{trip.data.pricing_mode || "—"}</KeyValue>
                <KeyValue label="Driver">{trip.data.driver?.name ?? "—"}</KeyValue>
              </div>
            </Card>
          )}
        </div>
      </div>

      <Modal
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        title="Resolve ticket"
        footer={
          <Button onClick={() => resolve.mutate()} disabled={!resolution.trim()} loading={resolve.isPending}>
            Resolve{Number(refund) > 0 ? ` & refund ${inr(refund)}` : ""}
          </Button>
        }
      >
        <Field label="Resolution (sent to the customer)">
          <Textarea value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder="We've reviewed your trip and…" />
        </Field>
        {t.trip && can("payments.refund") && (
          <Field label="Refund to wallet (₹)" hint={`Up to the trip fare of ${inr(trip.data?.fare_total)}. Posted to the ledger as a platform expense.`} className="mt-3">
            <Input type="number" min={0} value={refund} onChange={(e) => setRefund(e.target.value)} />
          </Field>
        )}
      </Modal>
    </>
  );
}
