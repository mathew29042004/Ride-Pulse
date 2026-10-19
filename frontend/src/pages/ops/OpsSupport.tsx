import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { Badge, Card, Input, PageHeader, Pagination, Segmented, StatusBadge, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { Paginated, Ticket } from "@/lib/types";
import { rowLink } from "@/lib/rowLink";

function Sla({ due, open }: { due: string; open: boolean }) {
  const now = useNow(30_000);
  if (!open) return <span className="text-xs text-muted">—</span>;
  const mins = Math.round((new Date(due).getTime() - now) / 60000);
  const overdue = mins < 0;
  const text = Math.abs(mins) < 60 ? `${Math.abs(mins)} min` : `${Math.round(Math.abs(mins) / 60)} h`;
  return <span className={clsx("text-xs font-semibold", overdue ? "text-danger" : mins < 60 ? "text-amber-600" : "text-muted")}>{overdue ? `${text} overdue` : `due in ${text}`}</span>;
}

export default function OpsSupport() {
  const navigate = useNavigate();
  const [view, setView] = useState<"open" | "mine" | "resolved">("open");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const qs = new URLSearchParams({ page: String(page), search, ordering: view === "resolved" ? "-created_at" : "sla_due_at" });
  qs.set("open", view === "resolved" ? "false" : "true");
  if (view === "mine") qs.set("mine", "true");
  const tickets = useQuery({
    queryKey: ["tickets", "queue", view, qs.toString()],
    queryFn: () => api.get<Paginated<Ticket>>(`support/tickets/?${qs}`),
    refetchInterval: 15_000,
  });
  const rows = tickets.data?.results ?? [];

  return (
    <>
      <PageHeader
        title="Support"
        subtitle="Tickets are auto-assigned to the least-busy agent and prioritised by category"
        actions={
          <Segmented
            value={view}
            onChange={(v) => { setView(v); setPage(1); }}
            options={[
              { value: "open", label: "Open queue" },
              { value: "mine", label: "Assigned to me" },
              { value: "resolved", label: "Resolved" },
            ]}
          />
        }
      />
      <Card>
        <div className="border-b border-line p-3">
          <div className="relative max-w-md">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Ticket, subject, email or trip" className="pl-9" />
          </div>
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Ticket</Th>
              <Th>From</Th>
              <Th>Priority</Th>
              <Th>Status</Th>
              <Th>Assignee</Th>
              <Th>SLA</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} {...rowLink(() => navigate(`/ops/support/${t.id}`))} className="cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2">
                <Td>
                  <div className="font-semibold">{t.subject}</div>
                  <div className="text-xs text-muted">
                    {t.ticket_number} · {t.category.replace(/_/g, " ").toLowerCase()} {t.trip_number && `· ${t.trip_number}`} · {ago(t.created_at)}
                  </div>
                </Td>
                <Td>{t.raised_by}</Td>
                <Td>
                  <StatusBadge status={t.priority} />
                  {t.escalated && <Badge tone="danger" className="ml-1">escalated</Badge>}
                </Td>
                <Td>
                  <StatusBadge status={t.status === "IN_PROGRESS" ? "IN_PROGRESS_TICKET" : t.status} label={t.status.replace(/_/g, " ").toLowerCase()} />
                </Td>
                <Td>{t.assigned_to ?? <span className="text-muted">Unassigned</span>}</Td>
                <Td>
                  <Sla due={t.sla_due_at} open={!["RESOLVED", "CLOSED"].includes(t.status)} />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {tickets.data && <Pagination page={page} count={tickets.data.count} onChange={setPage} />}
      </Card>
    </>
  );
}
