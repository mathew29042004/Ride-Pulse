/** Ops → Vehicle loans: approve or decline applications and watch the loan book (outstanding,
 * arrears). EMIs are taken from earnings in the weekly payout run. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Field, Input, Modal, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";

interface Loan {
  id: number;
  driver: string;
  city: string;
  vehicle: string;
  purpose_label: string;
  details: string;
  note: string;
  principal: string;
  tenure_weeks: number;
  weekly_emi: string;
  outstanding: string;
  arrears: string;
  status: string;
  status_label: string;
  requested_at: string;
}

export default function OpsLoans() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["ops", "loans"],
    queryFn: () => api.get<{ book: { n: number; outstanding: string | null; arrears: string | null }; loans: Loan[] }>("ops/loans/"),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve, note = "" }: { id: number; approve: boolean; note?: string }) => api.post(`ops/loans/${id}/decide/`, { approve, note }),
    onSuccess: () => {
      setDeclining(null);
      setReason("");
      qc.invalidateQueries({ queryKey: ["ops", "loans"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong."),
  });
  const book = q.data?.book;
  const [declining, setDeclining] = useState<Loan | null>(null);
  const [reason, setReason] = useState("");
  return (
    <>
      <PageHeader title="Vehicle loans" subtitle="Through our partner NBFC at 14% a year. EMIs come out of weekly earnings before payout; at most half the week's balance, and drivers always keep ₹1,500. Shortfalls carry over with no penalty." />
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Card className="p-3"><Stat label="Active loans" value={book?.n ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Outstanding" value={inr(book?.outstanding ?? 0, { whole: true })} /></Card>
        <Card className="p-3"><Stat label="In arrears" value={inr(book?.arrears ?? 0, { whole: true })} /></Card>
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <thead>
            <tr><Th>Driver</Th><Th>Vehicle and reason</Th><Th>Amount</Th><Th>EMI</Th><Th>Left</Th><Th>Arrears</Th><Th>Status</Th><Th /></tr>
          </thead>
          <tbody>
            {q.data?.loans.map((l) => (
              <tr key={l.id}>
                <Td>{l.driver}<div className="text-xs text-muted">{l.city} · {dateTime(l.requested_at)}</div></Td>
                <Td>
                  {l.vehicle}
                  <div className="text-xs text-muted">{l.purpose_label} · {l.tenure_weeks / 52} yr</div>
                  {l.details && <div className="text-xs italic">“{l.details}”</div>}
                  {l.status === "REJECTED" && l.note && <div className="text-xs text-danger">Declined: {l.note}</div>}
                </Td>
                <Td>{inr(l.principal, { whole: true })}</Td>
                <Td>{inr(l.weekly_emi)}</Td>
                <Td>{inr(l.outstanding, { whole: true })}</Td>
                <Td className={Number(l.arrears) > 0 ? "text-danger" : ""}>{inr(l.arrears)}</Td>
                <Td><Badge tone={l.status === "ACTIVE" ? "brand" : l.status === "REQUESTED" ? "warning" : "neutral"}>{l.status_label}</Badge></Td>
                <Td>
                  {l.status === "REQUESTED" && (
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => decide.mutate({ id: l.id, approve: true })}>Approve</Button>
                      <Button size="sm" variant="secondary" onClick={() => setDeclining(l)}>Decline</Button>
                    </div>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Modal open={!!declining} onClose={() => setDeclining(null)} title={`Decline ${declining?.driver ?? ""}'s loan`}>
        <Field label="Reason (the driver sees this)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder="e.g. The vehicle is older than 8 years" />
        </Field>
        <Button className="mt-3" block variant="danger" disabled={reason.trim().length < 5} loading={decide.isPending} onClick={() => declining && decide.mutate({ id: declining.id, approve: false, note: reason })}>
          Decline
        </Button>
      </Modal>
    </>
  );
}
