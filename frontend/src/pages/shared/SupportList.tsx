import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, LifeBuoy } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Button, EmptyState, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import type { Paginated, Ticket } from "@/lib/types";

import { HelpModal } from "../rider/RiderTrip";

export default function SupportList({ base }: { base: string }) {
  const [open, setOpen] = useState(false);
  const tickets = useQuery({ queryKey: ["tickets", "mine"], queryFn: () => api.get<Paginated<Ticket>>("support/tickets/") });
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <Link to={`${base}/account`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted">
        <ArrowLeft className="size-4" /> Account
      </Link>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Help</h1>
        <Button size="sm" onClick={() => setOpen(true)}>
          New ticket
        </Button>
      </div>
      <div className="mt-4 divide-y divide-line">
        {tickets.data?.results.length === 0 && (
          <EmptyState icon={<LifeBuoy />} title="No tickets">
            Need help with a trip or a payment? Open a ticket and our team will reply here.
          </EmptyState>
        )}
        {tickets.data?.results.map((t) => (
          <Link key={t.id} to={`${base}/support/${t.id}`} className="flex items-center gap-3 py-3.5">
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{t.subject}</div>
              <div className="text-xs text-muted">
                {t.ticket_number} · {t.trip_number ?? "General"} · {ago(t.created_at)}
              </div>
            </div>
            <StatusBadge status={t.status} />
            <ChevronRight className="size-4 text-muted" />
          </Link>
        ))}
      </div>
      <HelpModal open={open} onClose={() => setOpen(false)} base={base} />
    </div>
  );
}
