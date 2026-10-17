/** Ops → City P&L: revenue and costs by city for a month, from the ledger (estimates labelled),
 * against each city's budget. The bottom line is a contribution, before company-wide costs. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useState } from "react";
import { toast } from "sonner";

import { Card, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { inr } from "@/lib/format";

interface Row {
  city_id: number;
  slug?: string;
  city: string;
  state: string;
  trips: number;
  gmv: string;
  commission: string;
  fees: string;
  revenue: string;
  promotions: string;
  refunds: string;
  card_fees_est: string;
  support_est: string;
  costs: string;
  contribution: string;
  margin: number | null;
  gst_collected: string;
  budget?: { revenue: string; promotions: string; revenue_vs_budget: number | null; promotions_over: boolean };
}
interface Report {
  month: string;
  cities: Row[];
  not_city: Row | null;
  totals: Record<string, string | number>;
  assumptions: Record<string, string>;
}

const thisMonth = () => new Date().toISOString().slice(0, 7);
const whole = (v: string | number) => inr(v, { whole: true });

export default function OpsPnl() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [month, setMonth] = useState(thisMonth());
  const q = useQuery({ queryKey: ["pnl", month], queryFn: () => api.get<Report>(`analytics/pnl/?month=${month}`) });
  const budget = useMutation({
    mutationFn: (body: { city: string; revenue: string; promotions: string }) => api.post("analytics/pnl/", { ...body, month: `${month}-01` }),
    onSuccess: () => {
      toast.success("Budget saved");
      qc.invalidateQueries({ queryKey: ["pnl"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't save."),
  });
  const r = q.data;
  const t = r?.totals;
  return (
    <>
      <PageHeader
        title="City P&L"
        subtitle="Revenue and costs by city from the ledger (each transaction counts for its trip's city). Card gateway fees and support cost are estimates. The bottom line is a contribution, before salaries, marketing, offices and technology. GST is collected for the government and kept out of revenue."
        actions={<input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="Month" />}
      />
      {t && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="Trips" value={Number(t.trips).toLocaleString("en-IN")} sub={`${whole(t.gmv)} in fares`} />
          <Stat label="Revenue" value={whole(t.revenue)} tone="brand" />
          <Stat label="Costs" value={whole(t.costs)} sub={`${whole(t.promotions)} promotions`} />
          <Stat label="Contribution" value={whole(t.contribution)} tone="info" />
          <Stat label="GST collected" value={whole(t.gst_collected)} sub="owed to the government" />
        </div>
      )}
      <Card className="mt-4 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>City</Th>
              <Th className="text-right">Trips</Th>
              <Th className="text-right">Revenue</Th>
              <Th className="text-right">Promotions</Th>
              <Th className="text-right">Refunds</Th>
              <Th className="text-right">Card fees*</Th>
              <Th className="text-right">Support*</Th>
              <Th className="text-right">Contribution</Th>
              <Th className="text-right">vs budget</Th>
            </tr>
          </thead>
          <tbody>
            {[...(r?.cities ?? []), ...(r?.not_city ? [{ ...r.not_city, city: "Not tied to a city", state: "Ride Pass, bonuses", city_id: 0 }] : [])].map((row) => (
              <tr key={row.city_id} className="border-t border-line">
                <Td>
                  <div className="font-semibold">{row.city}</div>
                  <div className="text-xs text-muted">{row.state}</div>
                </Td>
                <Td className="text-right">{row.trips}</Td>
                <Td className="text-right">{whole(row.revenue)}</Td>
                <Td className={clsx("text-right", row.budget?.promotions_over && "font-semibold text-danger")}>{whole(row.promotions)}</Td>
                <Td className="text-right">{whole(row.refunds)}</Td>
                <Td className="text-right text-muted">{whole(row.card_fees_est)}</Td>
                <Td className="text-right text-muted">{whole(row.support_est)}</Td>
                <Td className="text-right font-semibold">
                  {whole(row.contribution)}
                  {row.margin != null && <span className="block text-xs font-normal text-muted">{Math.round(row.margin * 100)}%</span>}
                </Td>
                <Td className="text-right text-xs">
                  {row.budget?.revenue_vs_budget != null ? (
                    <span className={row.budget.revenue_vs_budget >= 0 ? "text-brand" : "text-danger"}>
                      {row.budget.revenue_vs_budget >= 0 ? "+" : ""}
                      {Math.round(row.budget.revenue_vs_budget * 100)}%
                    </span>
                  ) : row.city_id && can("payouts.manage") ? (
                    <button
                      className="text-brand"
                      onClick={() => {
                        const revenue = window.prompt(`${row.city}: revenue budget for ${month} (₹)`);
                        const promotions = revenue && window.prompt(`${row.city}: promotions budget (₹)`);
                        if (revenue && promotions && row.slug) budget.mutate({ city: row.slug, revenue, promotions });
                      }}
                    >
                      Set budget
                    </button>
                  ) : (
                    "—"
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {r && <p className="p-3 text-xs text-muted">* Estimates: card fees at {r.assumptions.card_fee_percent}% of card fares (UPI has no merchant fee in India); support at ₹{r.assumptions.cost_per_ticket} per ticket.</p>}
      </Card>
    </>
  );
}
