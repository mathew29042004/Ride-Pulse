import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Avatar, Badge, Button, Card, Input, Modal, PageHeader, Pagination, Table, Td, Textarea, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, inr } from "@/lib/format";
import type { Paginated, Rider } from "@/lib/types";

export default function OpsRiders() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [blockedOnly, setBlockedOnly] = useState(false);
  const [target, setTarget] = useState<Rider | null>(null);
  const [reason, setReason] = useState("");
  const qs = new URLSearchParams({ page: String(page), search, ordering: "-completed_trips", ...(blockedOnly ? { is_blocked: "true" } : {}) });
  const riders = useQuery({ queryKey: ["riders", qs.toString()], queryFn: () => api.get<Paginated<Rider>>(`riders/?${qs}`) });
  const toggle = useMutation({
    mutationFn: (rider: Rider) => api.post(`riders/${rider.id}/${rider.is_blocked ? "unblock" : "block"}/`, { reason }),
    onSuccess: (_, rider) => {
      toast.success(rider.is_blocked ? "Rider unblocked" : "Rider blocked");
      setTarget(null);
      setReason("");
      qc.invalidateQueries({ queryKey: ["riders"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });

  return (
    <>
      <PageHeader title="Riders" subtitle="Customer accounts, dues and trust & safety" />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Name, email, phone or referral code" className="pl-9" />
          </div>
          <Button variant={blockedOnly ? "primary" : "outline"} onClick={() => { setBlockedOnly((b) => !b); setPage(1); }}>
            Blocked only
          </Button>
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Rider</Th>
              <Th>Phone</Th>
              <Th className="text-right">Rating</Th>
              <Th className="text-right">Trips</Th>
              <Th className="text-right">Wallet</Th>
              <Th>Joined</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {riders.data?.results.map((r) => (
              <tr key={r.id}>
                <Td>
                  <div className="flex items-center gap-3">
                    <Avatar name={r.name} size={34} />
                    <div>
                      <div className="font-semibold">
                        {r.name} {r.is_blocked && <Badge tone="danger">blocked</Badge>}
                      </div>
                      <div className="text-xs text-muted">{r.email}</div>
                    </div>
                  </div>
                </Td>
                <Td>{r.phone || "—"}</Td>
                <Td className="text-right">{Number(r.rating).toFixed(2)}</Td>
                <Td className="text-right">{r.completed_trips}</Td>
                <Td className={`text-right ${Number(r.wallet_balance) < 0 ? "font-semibold text-danger" : ""}`}>{inr(r.wallet_balance)}</Td>
                <Td>{date(r.created_at)}</Td>
                <Td className="text-right">
                  {can("riders.manage") && (
                    <Button size="sm" variant={r.is_blocked ? "outline" : "ghost"} onClick={() => setTarget(r)}>
                      {r.is_blocked ? "Unblock" : "Block"}
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {riders.data && <Pagination page={page} count={riders.data.count} onChange={setPage} />}
      </Card>
      <Modal
        open={!!target}
        onClose={() => setTarget(null)}
        title={target?.is_blocked ? `Unblock ${target?.name}?` : `Block ${target?.name}?`}
        footer={
          <Button variant={target?.is_blocked ? "primary" : "danger"} onClick={() => target && toggle.mutate(target)} loading={toggle.isPending} disabled={!target?.is_blocked && !reason.trim()}>
            {target?.is_blocked ? "Unblock" : "Block rider"}
          </Button>
        }
      >
        {target?.is_blocked ? (
          <p className="text-sm text-muted">Blocked because: {target.blocked_reason}</p>
        ) : (
          <>
            <p className="mb-3 text-sm text-muted">Blocked riders can't book rides. The action is recorded in the audit trail.</p>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" />
          </>
        )}
      </Modal>
    </>
  );
}
