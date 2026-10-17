/** Ops → GST: the month's GSTR-1 data (business invoices by GSTIN, consumer sales by state) and
 * each business invoice's e-invoice JSON (INV-01) to upload to the invoice portal. */

import { useQuery } from "@tanstack/react-query";
import { Download, FileJson } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Card, CardHeader, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, openFile } from "@/lib/api";
import { inr } from "@/lib/format";

interface Data {
  month: string;
  sac: string;
  b2b: { trip_id: number; buyer_gstin: string; buyer: string; invoice: string; date: string; place_of_supply: string; taxable: string; cgst: string; sgst: string }[];
  b2cs: { place_of_supply: string; rides: number; taxable: string; cgst: string; sgst: string; rate: number }[];
  totals: { taxable: string; tax: string; b2b_invoices: number };
  note: string;
}

export default function OpsGst() {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const q = useQuery({ queryKey: ["gst", month], queryFn: () => api.get<Data>(`gst/returns/?month=${month}`) });
  const d = q.data;
  const downloadInvoice = async (tripId: number, invoice: string) => {
    try {
      const data = await api.get<{ ready_to_upload: boolean; missing: string[]; invoice: unknown }>(`gst/e-invoice/${tripId}/`);
      if (!data.ready_to_upload) toast.warning(`Missing: ${data.missing.join(", ")}`);
      const blob = new Blob([JSON.stringify(data.invoice, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${invoice}.json`;
      link.click();
    } catch {
      toast.error("Couldn't build the e-invoice.");
    }
  };
  return (
    <>
      <PageHeader
        title="GST"
        subtitle={`GSTR-1 data and e-invoices (SAC ${d?.sac ?? "996412"}, CGST + SGST). Registering e-invoices for an IRN needs a GST account with a GST Suvidha Provider; these are the files to upload. Cancellation fees, which also carry GST, aren't included yet.`}
        actions={
          <div className="flex gap-2">
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="Month" />
            <Button variant="outline" icon={<Download className="size-4" />} onClick={() => openFile(`/api/v1/gst/returns/?month=${month}&export=csv`)}>
              CSV
            </Button>
          </div>
        }
      />
      {d && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Taxable value" value={inr(d.totals.taxable, { whole: true })} />
            <Stat label="GST (CGST + SGST)" value={inr(d.totals.tax, { whole: true })} tone="brand" />
            <Stat label="Business invoices" value={d.totals.b2b_invoices} />
          </div>
          <Card className="mt-4 overflow-x-auto">
            <div className="p-4 pb-0">
              <CardHeader title="Consumer rides by state (B2CS)" />
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>Place of supply</Th>
                  <Th className="text-right">Rides</Th>
                  <Th className="text-right">Taxable</Th>
                  <Th className="text-right">CGST</Th>
                  <Th className="text-right">SGST</Th>
                </tr>
              </thead>
              <tbody>
                {d.b2cs.map((r) => (
                  <tr key={r.place_of_supply} className="border-t border-line">
                    <Td>{r.place_of_supply}</Td>
                    <Td className="text-right">{r.rides}</Td>
                    <Td className="text-right">{inr(r.taxable)}</Td>
                    <Td className="text-right">{inr(r.cgst)}</Td>
                    <Td className="text-right">{inr(r.sgst)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          <Card className="mt-4 overflow-x-auto">
            <div className="p-4 pb-0">
              <CardHeader title="Business invoices (B2B)" />
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>Buyer</Th>
                  <Th>Invoice</Th>
                  <Th className="text-right">Taxable</Th>
                  <Th className="text-right">CGST + SGST</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {d.b2b.slice(0, 200).map((r) => (
                  <tr key={r.invoice} className="border-t border-line">
                    <Td>
                      {r.buyer}
                      <div className="font-mono text-xs text-muted">{r.buyer_gstin}</div>
                    </Td>
                    <Td className="text-xs">
                      {r.invoice}
                      <div className="text-muted">{r.date}</div>
                    </Td>
                    <Td className="text-right">{inr(r.taxable)}</Td>
                    <Td className="text-right">{inr(Number(r.cgst) + Number(r.sgst))}</Td>
                    <Td>
                      <Button size="sm" variant="ghost" icon={<FileJson className="size-4" />} onClick={() => downloadInvoice(r.trip_id, r.invoice)}>
                        e-invoice
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="p-3 text-xs text-muted">{d.note}</p>
          </Card>
        </>
      )}
    </>
  );
}
