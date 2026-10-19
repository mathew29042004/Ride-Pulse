/** Ops → My payslips: every employee's own salary slips, with a PDF for each month. */

import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";

import { Badge, Card, EmptyState, PageHeader } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { inr } from "@/lib/format";

import { SlipLines } from "./OpsPayroll";

interface Slip {
  id: number;
  month: string;
  paid_days: string;
  lop_days: string;
  earnings: [string, string][];
  deductions: [string, string][];
  gross: string;
  total_deductions: string;
  net: string;
  status_label: string;
  paid_at: string | null;
}

export default function OpsPayslips() {
  const q = useQuery({ queryKey: ["payslips"], queryFn: () => api.get<{ monthly_gross: string | null; payslips: Slip[] }>("work/payslips/") });
  return (
    <>
      <PageHeader title="My payslips" subtitle={q.data?.monthly_gross ? `Monthly gross salary ${inr(q.data.monthly_gross)}` : "Your salary slips appear here once HR approves them."} />
      {q.data && !q.data.payslips.length && <EmptyState icon={<FileText />} title="No payslips yet" />}
      <div className="space-y-3">
        {q.data?.payslips.map((s) => (
          <Card key={s.id} className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="font-semibold">
                {new Date(s.month).toLocaleDateString(undefined, { month: "long", year: "numeric" })}{" "}
                <Badge tone={s.paid_at ? "brand" : "warning"}>{s.status_label}</Badge>
                <span className="ml-2 text-xs text-muted">{s.paid_days} paid days{Number(s.lop_days) > 0 ? ` · ${s.lop_days} loss of pay` : ""}</span>
              </div>
              <button className="text-sm font-semibold text-brand" onClick={() => openFile(`work/payslips/${s.id}/pdf/`)}>Download PDF</button>
            </div>
            <SlipLines slip={s} />
          </Card>
        ))}
      </div>
    </>
  );
}
