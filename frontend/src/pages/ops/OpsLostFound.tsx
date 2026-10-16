/** Ops: lost & found. Every open report (valuables first), items on their way back by parcel,
 * and the hub: items kept for 30 days before they're donated. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageSearch } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Card, PageHeader, Stat, StatusBadge, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";

interface Row {
  id: number;
  trip_id: number;
  trip_number: string;
  rider_name: string;
  driver_name: string | null;
  city: string;
  description: string;
  category: string;
  status: string;
  status_label: string;
  driver_note: string;
  return_trip_id: number | null;
  found_at: string | null;
  hub_at: string | null;
  created_at: string;
}

const VALUABLES = new Set(["PHONE", "WALLET", "KEYS", "DOCUMENTS"]);
const FILTERS = [
  ["", "All open"],
  ["REPORTED", "Waiting for driver"],
  ["FOUND", "Found"],
  ["ON_THE_WAY", "Being delivered"],
  ["AT_HUB", "At the hub"],
  ["NOT_FOUND", "Not found"],
] as const;

export default function OpsLostFound() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["ops", "lost-found"], queryFn: () => api.get<Row[]>("ops/lost-found/"), refetchInterval: 30_000 });
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: "hub" | "returned" | "dispose" }) => api.post(`ops/lost-found/${id}/${verb}/`),
    onSuccess: () => {
      toast.success("Updated");
      qc.invalidateQueries({ queryKey: ["ops", "lost-found"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Something went wrong."),
  });
  const all = q.data ?? [];
  const rows = all
    .filter((r) => !filter || r.status === filter)
    .sort((a, b) => Number(VALUABLES.has(b.category)) - Number(VALUABLES.has(a.category)));
  const count = (s: string) => all.filter((r) => r.status === s).length;
  return (
    <>
      <PageHeader title="Lost & found" subtitle="Valuables (phones, wallets, keys, documents) are urgent. Found items can go back to the rider as a bike parcel; anything not collected in 7 days goes to the city hub, and is donated after 30 days there." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Waiting for the driver" value={q.data ? count("REPORTED") : "—"} icon={<PackageSearch className="size-4" />} tone="warning" />
        <Stat label="Found, to hand back" value={q.data ? count("FOUND") : "—"} tone="brand" />
        <Stat label="Being delivered" value={q.data ? count("ON_THE_WAY") : "—"} tone="info" />
        <Stat label="At the hub" value={q.data ? count("AT_HUB") : "—"} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {FILTERS.map(([key, label]) => (
          <Button key={key || "all"} size="sm" variant={filter === key ? "primary" : "outline"} onClick={() => setFilter(key)}>
            {label}
          </Button>
        ))}
      </div>
      <Card className="mt-3 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>Item</Th>
              <Th>Trip</Th>
              <Th>Rider / driver</Th>
              <Th>Status</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <Td>
                  <div className="font-semibold">
                    {r.description} {VALUABLES.has(r.category) && <span className="ml-1 rounded bg-danger/15 px-1.5 text-[10px] font-bold text-danger">VALUABLE</span>}
                  </div>
                  <div className="text-xs text-muted">
                    {r.category.toLowerCase()} · reported {ago(r.created_at)}
                    {r.driver_note && ` · driver: “${r.driver_note}”`}
                  </div>
                </Td>
                <Td>
                  <Link className="text-brand" to={`/ops/trips/${r.trip_id}`}>
                    {r.trip_number}
                  </Link>
                  <div className="text-xs text-muted">{r.city}</div>
                </Td>
                <Td>
                  {r.rider_name}
                  <div className="text-xs text-muted">{r.driver_name ?? "—"}</div>
                </Td>
                <Td>
                  <StatusBadge status={r.status} label={r.status_label} />
                  {r.hub_at && <div className="text-xs text-muted">at hub {ago(r.hub_at)}</div>}
                </Td>
                <Td>
                  <div className="flex gap-1">
                    {r.status === "FOUND" && (
                      <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: r.id, verb: "hub" })}>
                        To hub
                      </Button>
                    )}
                    {(r.status === "FOUND" || r.status === "AT_HUB") && (
                      <Button size="sm" variant="outline" onClick={() => act.mutate({ id: r.id, verb: "returned" })}>
                        Collected
                      </Button>
                    )}
                    {r.status === "AT_HUB" && (
                      <Button size="sm" variant="ghost" onClick={() => window.confirm("Mark as unclaimed and donated?") && act.mutate({ id: r.id, verb: "dispose" })}>
                        Donate
                      </Button>
                    )}
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {rows.length === 0 && <p className="p-4 text-sm text-muted">Nothing here.</p>}
      </Card>
    </>
  );
}
