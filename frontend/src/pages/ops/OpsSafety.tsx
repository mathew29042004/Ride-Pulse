import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, PinMarker } from "@/components/map";
import { OpsRideChecks } from "@/components/SafetyPlus";
import { Button, Card, CardHeader, EmptyState, KeyValue, PageHeader, StatusBadge, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, dateTime } from "@/lib/format";
import type { Incident, Paginated } from "@/lib/types";

export default function OpsSafety() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: () => api.get<Paginated<Incident>>("safety/incidents/?page_size=50"), refetchInterval: 8_000 });
  const list = incidents.data?.results ?? [];
  const selected = list.find((i) => String(i.id) === id) ?? list.find((i) => i.status !== "RESOLVED") ?? list[0];
  const refresh = () => qc.invalidateQueries({ queryKey: ["incidents"] });
  const ack = useMutation({ mutationFn: (i: Incident) => api.post(`safety/incidents/${i.id}/acknowledge/`), onSuccess: () => { toast.success("Acknowledged. Call the rider and driver now."); refresh(); }, onError: (e) => toast.error((e as Error).message) });
  const resolve = useMutation({ mutationFn: (i: Incident) => api.post(`safety/incidents/${i.id}/resolve/`, { note }), onSuccess: () => { toast.success("Incident resolved"); setNote(""); refresh(); }, onError: (e) => toast.error((e as Error).message) });

  return (
    <>
      <PageHeader title="Safety desk" subtitle="SOS alerts from riders and drivers. Acknowledge within a minute, call both parties, then resolve." />
      {list.length === 0 ? (
        <Card>
          <EmptyState icon={<ShieldCheck />} title="No SOS alerts">
            When someone presses SOS during a trip, it appears here instantly with the trip's location.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <Card className="max-h-[70vh] overflow-y-auto">
            {list.map((i) => (
              <button
                key={i.id}
                onClick={() => navigate(`/ops/safety/${i.id}`)}
                className={clsx("flex w-full items-center gap-3 border-b border-line px-5 py-3 text-left last:border-0 hover:bg-surface-2", selected?.id === i.id && "bg-surface-2")}
              >
                <ShieldAlert className={clsx("size-5", i.status === "RESOLVED" ? "text-muted" : "text-danger")} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold">
                    {i.incident_number} · {i.trip_number}
                  </div>
                  <div className="truncate text-xs text-muted">
                    {i.raised_by} · {ago(i.created_at)}
                  </div>
                </div>
                <StatusBadge status={i.status} />
              </button>
            ))}
          </Card>
          {selected && (
            <Card>
              <CardHeader title={`${selected.incident_number} · ${selected.trip_number}`} subtitle={selected.note || "SOS button pressed"} action={<StatusBadge status={selected.status} />} />
              {selected.lat !== null && selected.lng !== null && (
                <div className="h-64">
                  <BaseMap center={[selected.lat, selected.lng]} zoom={15} zoomControl>
                    <PinMarker lat={selected.lat} lng={selected.lng} kind="me" label="SOS location" />
                  </BaseMap>
                </div>
              )}
              <div className="px-5 py-3">
                <KeyValue label="Raised by">{selected.raised_by}</KeyValue>
                <KeyValue label="Raised at">{dateTime(selected.created_at)}</KeyValue>
                <KeyValue label="Acknowledged">{selected.acknowledged_by ? `${selected.acknowledged_by} · ${dateTime(selected.acknowledged_at)}` : "Not yet"}</KeyValue>
                <KeyValue label="Trip">
                  <Link to={`/ops/trips/${selected.trip}`} className="font-semibold hover:underline">
                    Open trip →
                  </Link>
                </KeyValue>
                {selected.resolution_note && <KeyValue label="Resolution">{selected.resolution_note}</KeyValue>}
              </div>
              {selected.status !== "RESOLVED" && (
                <div className="space-y-3 border-t border-line p-5">
                  {selected.status === "OPEN" && (
                    <Button variant="danger" block onClick={() => ack.mutate(selected)} loading={ack.isPending}>
                      Acknowledge & call now
                    </Button>
                  )}
                  <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened and how it was resolved" />
                  <Button block variant="outline" onClick={() => resolve.mutate(selected)} disabled={!note.trim()} loading={resolve.isPending}>
                    Resolve incident
                  </Button>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
      <OpsRideChecks />
    </>
  );
}
