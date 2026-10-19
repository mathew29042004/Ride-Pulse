/** Ops → Approvals: everything waiting on me (team leave, claims and attendance fixes, large
 * refunds, loans, job applications, the chief's decisions), each linking to where it's decided. */

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Inbox } from "lucide-react";
import { Link } from "react-router";

import { Badge, Card, EmptyState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export interface ApprovalItem {
  kind: string;
  title: string;
  detail: string;
  link: string;
}

export const useApprovals = () =>
  useQuery({ queryKey: ["approvals"], queryFn: () => api.get<{ count: number; items: ApprovalItem[] }>("approvals/"), refetchInterval: 60_000 });

const TONE: Record<string, "warning" | "info" | "brand" | "danger" | "neutral"> = {
  Leave: "info",
  Expense: "brand",
  Attendance: "neutral",
  Refund: "warning",
  Loan: "warning",
  Application: "info",
  Decision: "danger",
};

export default function OpsApprovals() {
  const q = useApprovals();
  const items = q.data?.items ?? [];
  const kinds = [...new Set(items.map((i) => i.kind))];
  return (
    <>
      <PageHeader title="Approvals" subtitle="Everything waiting on you, from every part of the console." />
      {q.data && !items.length && (
        <Card>
          <EmptyState icon={<Inbox />} title="You're all caught up">Nothing is waiting on you right now.</EmptyState>
        </Card>
      )}
      <div className="space-y-4">
        {kinds.map((k) => (
          <Card key={k}>
            <div className="flex items-center gap-2 border-b border-line px-5 py-3 font-semibold">
              {k} <Badge tone={TONE[k] ?? "neutral"}>{items.filter((i) => i.kind === k).length}</Badge>
            </div>
            <div className="divide-y divide-line">
              {items
                .filter((i) => i.kind === k)
                .map((i, n) => (
                  <Link key={n} to={i.link} className="flex items-center justify-between gap-3 px-5 py-3 text-sm hover:bg-surface-2">
                    <div className="min-w-0">
                      <div className="font-medium">{i.title}</div>
                      {i.detail && <div className="truncate text-xs text-muted">{i.detail}</div>}
                    </div>
                    <ArrowRight className="size-4 shrink-0 text-muted" />
                  </Link>
                ))}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
