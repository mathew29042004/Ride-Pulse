/** Ops → Fuel prices: record petrol/diesel/CNG prices per state and apply the suggested per-km
 * fare change for each ride type, so drivers' margins don't shrink when fuel goes up. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Card, CardHeader, Input, PageHeader, Select, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";

interface Row {
  ride_type: string;
  name: string;
  fuel: string;
  mileage: string;
  basis_price: string;
  current_price: string;
  cost_per_km_change: string;
  suggested_change: string;
  current_per_km: string;
  driver_loss_per_day: string;
  cities: number;
}
interface Data {
  states: string[];
  state: string;
  km_per_driver_day: string;
  rows: Row[];
  history: { fuel: string; price: string; effective_on: string }[];
}

export default function OpsFuel() {
  const qc = useQueryClient();
  const [state, setState] = useState("");
  const q = useQuery({ queryKey: ["fuel", state], queryFn: () => api.get<Data>(`ops/fuel/${state ? `?state=${encodeURIComponent(state)}` : ""}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["fuel"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const [fuelType, setFuelType] = useState("CNG");
  const [price, setPrice] = useState("");
  const d = q.data;
  const current = state || d?.state || "";
  const record = useMutation({ mutationFn: () => api.post("ops/fuel/", { state: current, fuel: fuelType, price }), onSuccess: () => { setPrice(""); refresh(); }, onError: fail });
  const apply = useMutation({ mutationFn: (code: string) => api.post<{ updated: number }>("ops/fuel/apply/", { state: current, ride_type: code }), onSuccess: (r) => { toast.success(`${r.updated} fare rules updated`); refresh(); }, onError: fail });
  return (
    <>
      <PageHeader title="Fuel prices" subtitle={`When fuel prices change, the per-km fare should move with drivers' fuel cost per km. A driver here drives about ${d?.km_per_driver_day ?? "—"} km a day.`} actions={
        <Select value={current} onChange={(e) => setState(e.target.value)} aria-label="State" className="!w-56 !py-2">
          {d?.states.map((s) => <option key={s}>{s}</option>)}
        </Select>
      } />
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card className="space-y-3 p-4">
          <CardHeader title="Record a new price" />
          <Select value={fuelType} onChange={(e) => setFuelType(e.target.value)} aria-label="Fuel">
            <option value="CNG">CNG (₹/kg)</option><option value="PETROL">Petrol (₹/litre)</option><option value="DIESEL">Diesel (₹/litre)</option>
          </Select>
          <Input type="number" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="₹" aria-label="Price" />
          <Button block disabled={!price} loading={record.isPending} onClick={() => record.mutate()}>Save price</Button>
          <div className="space-y-1 text-xs text-muted">
            {d?.history.map((h, i) => <div key={i}>{h.effective_on} · {h.fuel} {inr(h.price)}</div>)}
          </div>
        </Card>
        <Card className="overflow-x-auto">
          <Table>
            <thead><tr><Th>Ride type</Th><Th>Fuel</Th><Th>Fares set at</Th><Th>Now</Th><Th>Cost/km change</Th><Th>Per km now</Th><Th>Suggested</Th><Th>Driver loses/day</Th><Th /></tr></thead>
            <tbody>
              {d?.rows.map((r) => (
                <tr key={r.ride_type}>
                  <Td>{r.name}<div className="text-xs text-muted">{r.mileage} km per unit · {r.cities} cities</div></Td>
                  <Td>{r.fuel}</Td>
                  <Td>{inr(r.basis_price)}</Td>
                  <Td>{inr(r.current_price)}</Td>
                  <Td>{Number(r.cost_per_km_change) >= 0 ? "+" : ""}{inr(r.cost_per_km_change)}</Td>
                  <Td>{inr(r.current_per_km)}</Td>
                  <Td className="font-semibold">{Number(r.suggested_change) >= 0 ? "+" : ""}{inr(r.suggested_change)}/km</Td>
                  <Td className={Number(r.driver_loss_per_day) > 0 ? "text-danger" : ""}>{inr(r.driver_loss_per_day, { whole: true })}</Td>
                  <Td>{Number(r.suggested_change) !== 0 && <Button size="sm" loading={apply.isPending} onClick={() => apply.mutate(r.ride_type)}>Apply</Button>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {d && !d.rows.length && <p className="p-4 text-sm text-muted">No fuel prices recorded for {current} yet.</p>}
        </Card>
      </div>
    </>
  );
}
