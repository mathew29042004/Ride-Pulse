import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, Send } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { Badge, Input, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import type { Ticket } from "@/lib/types";

export default function TicketThread({ base }: { base: string }) {
  const { id } = useParams();
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const ticket = useQuery({ queryKey: ["tickets", id], queryFn: () => api.get<Ticket>(`support/tickets/${id}/`), refetchInterval: 10_000 });
  const reply = useMutation({
    mutationFn: () => api.post<Ticket>(`support/tickets/${id}/reply/`, { body }),
    onSuccess: () => {
      setBody("");
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });

  if (!ticket.data) return <Spinner className="mx-auto mt-20" />;
  const t = ticket.data;
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-5 pt-5 pb-3">
        <Link to={`${base}/support`} className="mb-2 inline-flex items-center gap-1 text-sm text-muted">
          <ArrowLeft className="size-4" /> Tickets
        </Link>
        <h1 className="font-bold">{t.subject}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
          {t.ticket_number} <StatusBadge status={t.status} /> {t.trip_number && <Badge>{t.trip_number}</Badge>}
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-ink px-4 py-2.5 text-sm text-ink-fg ml-auto">
          {t.description}
          <div className="mt-1 text-[10px] opacity-60">{dateTime(t.created_at)}</div>
        </div>
        {t.messages.map((m) => (
          <div key={m.id} className={clsx("max-w-[85%] rounded-2xl px-4 py-2.5 text-sm", m.author_is_staff ? "rounded-tl-sm bg-surface-3" : "ml-auto rounded-tr-sm bg-ink text-ink-fg")}>
            {m.author_is_staff && <div className="mb-0.5 text-[11px] font-semibold text-brand-strong">{m.author} · Ride Pulse support</div>}
            {m.body}
            <div className="mt-1 text-[10px] opacity-60">{dateTime(m.created_at)}</div>
          </div>
        ))}
        {t.status === "RESOLVED" && (
          <div className="rounded-2xl border border-brand/40 bg-brand-soft p-3 text-sm">
            <div className="font-semibold">Resolved</div>
            <div className="text-muted">{t.resolution}</div>
            {Number(t.refund_amount) > 0 && <div className="mt-1 font-semibold text-brand-strong">{inr(t.refund_amount)} refunded to your wallet</div>}
            <RateHelp ticketId={t.id} rating={t.rating ?? null} />
          </div>
        )}
      </div>
      {!["RESOLVED", "CLOSED"].includes(t.status) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim()) reply.mutate();
          }}
          className="flex gap-2 border-t border-line p-3"
        >
          <Input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a message" />
          <button type="submit" className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-ink text-ink-fg" aria-label="Send" disabled={reply.isPending}>
            <Send className="size-4" />
          </button>
        </form>
      )}
    </div>
  );
}


/** CSAT: one tap, 1 to 5, once the ticket is resolved. */
function RateHelp({ ticketId, rating }: { ticketId: number; rating: number | null }) {
  const qc = useQueryClient();
  const [score, setScore] = useState<number | null>(rating);
  const send = useMutation({
    mutationFn: (value: number) => api.post(`me/tickets/${ticketId}/rate/`, { score: value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["support"] }),
  });
  return (
    <div className="mt-3 border-t border-brand/30 pt-2">
      <div className="text-xs font-semibold">{rating || send.isSuccess ? "Thanks for rating us" : "How was the help you got?"}</div>
      <div className="mt-1 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            disabled={!!rating || send.isSuccess || send.isPending}
            onClick={() => {
              setScore(n);
              send.mutate(n);
            }}
            className={clsx("text-2xl leading-none", (score ?? 0) >= n ? "text-amber-500" : "text-muted/40")}
            aria-label={`${n} star${n > 1 ? "s" : ""}`}
          >
            ★
          </button>
        ))}
      </div>
    </div>
  );
}
