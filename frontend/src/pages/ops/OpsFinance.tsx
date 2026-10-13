import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Landmark } from "lucide-react";
import { toast } from "sonner";

import { Button, Card, CardHeader, PageHeader, Stat, StatusBadge, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, dateTime, inr } from "@/lib/format";
import type { Paginated, Payout } from "@/lib/types";

interface Ledger {
  accounts: Record<string, string>;
  integrity: { balanced: boolean; unbalanced_transactions: number[]; mismatched_wallets: number[] };
}

interface PaymentRow {
  id: number;
  reference: string;
  user: string;
  purpose: string;
  method: string;
  amount: string;
  status: string;
  failure_reason: string;
  created_at: string;
}

const ACCOUNT_LABELS: Record<string, string> = {
  "platform:commission": "Commission earned",
  "platform:fees": "Booking & airport fees",
  "platform:promotions": "Promotions funded",
  "platform:refunds": "Refunds issued",
  "tax:gst_payable": "GST collected (payable)",
  "external:gateway": "Collected via gateway",
  "external:payouts_in_transit": "Payouts to banks",
};

export default function OpsFinance() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const ledger = useQuery({ queryKey: ["ledger"], queryFn: () => api.get<Ledger>("ledger/"), refetchInterval: 30_000 });
  const payouts = useQuery({ queryKey: ["payouts", "all"], queryFn: () => api.get<Paginated<Payout>>("payouts/?page_size=15") });
  const payments = useQuery({ queryKey: ["payments"], queryFn: () => api.get<Paginated<PaymentRow>>("payments/?page_size=12") });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["payouts"] });
    qc.invalidateQueries({ queryKey: ["ledger"] });
  };
  const generate = useMutation({
    mutationFn: () => api.post<Payout[]>("payouts/generate/"),
    onSuccess: (p) => {
      toast.success(p.length ? `Created ${p.length} payouts` : "No driver balances above the payout minimum");
      refresh();
    },
  });
  const settle = useMutation({
    mutationFn: ({ payout, ok }: { payout: Payout; ok: boolean }) =>
      api.post(`payouts/${payout.id}/${ok ? "mark-paid" : "mark-failed"}/`, ok ? { bank_reference: `UTR${Date.now().toString().slice(-10)}` } : { reason: "Invalid bank account" }),
    onSuccess: refresh,
  });
  const a = ledger.data?.accounts ?? {};
  const integrity = ledger.data?.integrity;

  return (
    <>
      <PageHeader title="Payments & payouts" subtitle="Every rupee is recorded in a double-entry ledger: each transaction's entries sum to zero" />
      <div className="grid gap-3 md:grid-cols-4">
        <Card className="flex items-center gap-3 p-4 md:col-span-1">
          {integrity?.balanced ? <CheckCircle2 className="size-9 text-brand" /> : <CircleAlert className="size-9 text-danger" />}
          <div>
            <div className="font-semibold">{integrity?.balanced ? "Ledger balanced" : "Ledger mismatch"}</div>
            <div className="text-xs text-muted">
              {integrity ? `${integrity.unbalanced_transactions.length} unbalanced · ${integrity.mismatched_wallets.length} wallet drifts` : "Checking…"}
            </div>
          </div>
        </Card>
        <Stat label="Commission earned" value={inr(a["platform:commission"], { whole: true })} tone="brand" />
        <Stat label="GST payable" value={inr(a["tax:gst_payable"], { whole: true })} tone="info" />
        <Stat label="Promotions funded" value={inr(Math.abs(Number(a["platform:promotions"] ?? 0)), { whole: true })} tone="warning" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.5fr]">
        <Card>
          <CardHeader title="Platform accounts" />
          <div className="divide-y divide-line">
            {Object.entries(ACCOUNT_LABELS).map(([key, label]) => (
              <div key={key} className="flex items-center justify-between px-5 py-2.5 text-sm">
                <div>
                  <div className="font-medium">{label}</div>
                  <div className="font-mono text-[11px] text-muted">{key}</div>
                </div>
                <div className="font-semibold">{inr(a[key])}</div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader
            title="Driver payouts"
            subtitle="Weekly, every Monday, for balances above ₹100"
            action={
              can("payouts.manage") && (
                <Button size="sm" icon={<Landmark className="size-4" />} onClick={() => generate.mutate()} loading={generate.isPending}>
                  Run weekly payouts
                </Button>
              )
            }
          />
          <Table>
            <thead>
              <tr>
                <Th>Payout</Th>
                <Th>Driver</Th>
                <Th className="text-right">Amount</Th>
                <Th>Status</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {payouts.data?.results.map((p) => (
                <tr key={p.id}>
                  <Td>
                    <div className="font-medium">{p.payout_number}</div>
                    <div className="text-xs text-muted">
                      {date(p.period_start)} – {date(p.period_end)}
                    </div>
                  </Td>
                  <Td>{p.driver_name}</Td>
                  <Td className="text-right font-semibold">{inr(p.amount)}</Td>
                  <Td>
                    <StatusBadge status={p.status} />
                  </Td>
                  <Td className="text-right whitespace-nowrap">
                    {p.status === "PENDING" && can("payouts.manage") && (
                      <>
                        <Button size="sm" variant="brand" onClick={() => settle.mutate({ payout: p, ok: true })}>
                          Mark paid
                        </Button>{" "}
                        <Button size="sm" variant="ghost" onClick={() => settle.mutate({ payout: p, ok: false })}>
                          Failed
                        </Button>
                      </>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Recent gateway payments" subtitle="UPI and card charges, with idempotency keys preventing double charges" />
        <Table>
          <thead>
            <tr>
              <Th>Reference</Th>
              <Th>User</Th>
              <Th>Purpose</Th>
              <Th>Method</Th>
              <Th className="text-right">Amount</Th>
              <Th>Status</Th>
              <Th>When</Th>
            </tr>
          </thead>
          <tbody>
            {payments.data?.results.map((p) => (
              <tr key={p.id}>
                <Td className="font-mono text-xs">{p.reference}</Td>
                <Td>{p.user}</Td>
                <Td>{p.purpose.toLowerCase()}</Td>
                <Td>{p.method}</Td>
                <Td className="text-right">{inr(p.amount)}</Td>
                <Td>
                  <StatusBadge status={p.status === "SUCCEEDED" ? "PAID" : "FAILED"} label={p.status.toLowerCase()} />
                  {p.failure_reason && <div className="text-xs text-muted">{p.failure_reason}</div>}
                </Td>
                <Td>{dateTime(p.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
