/** Ops → Payroll (HR): run the month from attendance and leave, check the payslips, approve,
 * then mark them paid with the bank transfer reference. Staff without a salary are listed. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Input, Modal, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";

interface Slip {
  id: number;
  name: string;
  role: string;
  paid_days: string;
  lop_days: string;
  gross: string;
  total_deductions: string;
  net: string;
  status: "DRAFT" | "APPROVED" | "PAID";
  status_label: string;
  earnings: [string, string][];
  deductions: [string, string][];
}
interface Board {
  month: string;
  people: number;
  by_status: Record<string, number>;
  gross: string;
  net: string;
  deductions: string;
  employer_cost: string;
  cost_to_company: string;
  lop_days: string;
  payslips: Slip[];
  without_salary: { user_id: number; name: string; title: string }[];
}

const lastMonth = () => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 7);
};

export default function OpsPayroll() {
  const qc = useQueryClient();
  const [month, setMonth] = useState(lastMonth());
  const key = ["payroll", month];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Board>(`work/payroll/?month=${month}-01`) });
  const set = (d: Board) => qc.setQueryData(key, d);
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const run = useMutation({ mutationFn: () => api.post<Board>("work/payroll/run/", { month: `${month}-01` }), onSuccess: (d) => { set(d); toast.success("Payslips calculated from attendance and leave."); }, onError: fail });
  const approve = useMutation({ mutationFn: () => api.post<Board>("work/payroll/approve/", { month: `${month}-01` }), onSuccess: set, onError: fail });
  const [paying, setPaying] = useState(false);
  const [ref, setRef] = useState("");
  const pay = useMutation({
    mutationFn: () => api.post<Board>("work/payroll/pay/", { month: `${month}-01`, bank_reference: ref }),
    onSuccess: (d) => { set(d); setPaying(false); setRef(""); toast.success("Marked paid. Everyone has been told."); },
    onError: fail,
  });
  const [salaryFor, setSalaryFor] = useState<{ user_id: number; name: string } | null>(null);
  const [gross, setGross] = useState("25000");
  const salary = useMutation({
    mutationFn: () => api.post("work/payroll/salary/", { user_id: salaryFor!.user_id, monthly_gross: gross }),
    onSuccess: () => { setSalaryFor(null); qc.invalidateQueries({ queryKey: ["payroll"] }); },
    onError: fail,
  });
  const [open, setOpen] = useState<Slip | null>(null);
  const b = q.data;
  return (
    <>
      <PageHeader
        title="Payroll"
        subtitle="Salaries from attendance and leave: absent days are loss of pay, approved leave is paid, overtime at 2x basic, ₹200 per night shift. PF, ESI, professional tax and TDS (new regime) are deducted."
        actions={
          <div className="flex items-center gap-2">
            <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" className="!w-40 !py-2" />
            <Button size="sm" variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>Run payroll</Button>
            <Button size="sm" variant="secondary" disabled={!b?.by_status.DRAFT} loading={approve.isPending} onClick={() => approve.mutate()}>Approve all</Button>
            <Button size="sm" disabled={!b?.by_status.APPROVED} onClick={() => setPaying(true)}>Mark paid</Button>
          </div>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Card className="p-3"><Stat label="People" value={b?.people ?? "—"} /></Card>
        <Card className="p-3"><Stat label="Gross" value={inr(b?.gross ?? 0, { whole: true })} /></Card>
        <Card className="p-3"><Stat label="Net pay" value={inr(b?.net ?? 0, { whole: true })} /></Card>
        <Card className="p-3"><Stat label="Cost to company" value={inr(b?.cost_to_company ?? 0, { whole: true })} sub={`employer PF/ESI ${inr(b?.employer_cost ?? 0, { whole: true })}`} /></Card>
        <Card className="p-3"><Stat label="Loss-of-pay days" value={b?.lop_days ?? "—"} /></Card>
      </div>
      {b && b.without_salary.length > 0 && (
        <Card className="mb-4 p-3 text-sm">
          <div className="mb-1 font-semibold">No salary set ({b.without_salary.length})</div>
          <div className="flex flex-wrap gap-1">
            {b.without_salary.map((p) => (
              <button key={p.user_id} className="rounded-full bg-surface-2 px-2 py-1 text-xs" onClick={() => setSalaryFor(p)}>{p.name} · {p.title}</button>
            ))}
          </div>
        </Card>
      )}
      <Card className="overflow-x-auto">
        <Table>
          <thead><tr><Th>Employee</Th><Th>Paid days</Th><Th>Gross</Th><Th>Deductions</Th><Th>Net</Th><Th>Status</Th><Th /></tr></thead>
          <tbody>
            {b?.payslips.map((s) => (
              <tr key={s.id}>
                <Td>{s.name}<div className="text-xs text-muted">{s.role}</div></Td>
                <Td>{s.paid_days}{Number(s.lop_days) > 0 && <span className="text-xs text-danger"> ({s.lop_days} LOP)</span>}</Td>
                <Td>{inr(s.gross)}</Td>
                <Td>{inr(s.total_deductions)}</Td>
                <Td className="font-semibold">{inr(s.net)}</Td>
                <Td><Badge tone={s.status === "PAID" ? "brand" : s.status === "APPROVED" ? "warning" : "neutral"}>{s.status_label}</Badge></Td>
                <Td>
                  <div className="flex gap-2 text-xs">
                    <button className="text-brand" onClick={() => setOpen(s)}>Details</button>
                    <button className="text-brand" onClick={() => openFile(`work/payslips/${s.id}/pdf/`)}>PDF</button>
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {b && !b.payslips.length && <p className="p-4 text-sm text-muted">No payslips for this month yet. Press Run payroll.</p>}
      </Card>
      <Modal open={paying} onClose={() => setPaying(false)} title="Mark the month paid">
        <p className="mb-2 text-sm text-muted">Enter the bank's reference for the salary transfer. Everyone gets their payslip.</p>
        <Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR / batch reference" aria-label="Bank reference" />
        <Button className="mt-3" block disabled={ref.trim().length < 4} loading={pay.isPending} onClick={() => pay.mutate()}>Mark paid</Button>
      </Modal>
      <Modal open={!!salaryFor} onClose={() => setSalaryFor(null)} title={`Salary for ${salaryFor?.name ?? ""}`}>
        <Input type="number" min={10000} step={500} value={gross} onChange={(e) => setGross(e.target.value)} aria-label="Monthly gross salary" />
        <Button className="mt-3" block loading={salary.isPending} onClick={() => salary.mutate()}>Save monthly gross</Button>
      </Modal>
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.name ?? ""}>
        {open && <SlipLines slip={open} />}
      </Modal>
    </>
  );
}

export function SlipLines({ slip }: { slip: Pick<Slip, "earnings" | "deductions" | "gross" | "total_deductions" | "net"> }) {
  return (
    <div className="grid gap-4 text-sm sm:grid-cols-2">
      <div>
        <div className="mb-1 font-semibold">Earnings</div>
        {slip.earnings.map(([label, amount]) => <div key={label} className="flex justify-between"><span>{label}</span><span>{inr(amount)}</span></div>)}
        <div className="mt-1 flex justify-between border-t border-line pt-1 font-semibold"><span>Gross</span><span>{inr(slip.gross)}</span></div>
      </div>
      <div>
        <div className="mb-1 font-semibold">Deductions</div>
        {slip.deductions.map(([label, amount]) => <div key={label} className="flex justify-between"><span>{label}</span><span>{inr(amount)}</span></div>)}
        <div className="mt-1 flex justify-between border-t border-line pt-1 font-semibold"><span>Total</span><span>{inr(slip.total_deductions)}</span></div>
      </div>
      <div className="flex justify-between rounded-xl bg-surface-2 p-2 font-bold sm:col-span-2"><span>Net pay</span><span>{inr(slip.net)}</span></div>
    </div>
  );
}
