import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Ban, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { BaseMap, CarMarker } from "@/components/map";
import { RideTypeArt } from "@/components/RideTypeArt";
import { Avatar, Button, Card, CardHeader, KeyValue, Modal, Spinner, Stat, StatusBadge, Table, Td, Textarea, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ago, date, dateTime, inr } from "@/lib/format";
import type { Driver, DriverDocument, Paginated, Trip } from "@/lib/types";

import { DocumentRow } from "./DocumentReview";

export default function OpsDriverDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const driver = useQuery({ queryKey: ["drivers", id], queryFn: () => api.get<Driver>(`drivers/${id}/`), refetchInterval: 10_000 });
  const docs = useQuery({ queryKey: ["drivers", id, "documents"], queryFn: () => api.get<DriverDocument[]>(`drivers/${id}/documents/`) });
  const trips = useQuery({ queryKey: ["trips", "driver", id], queryFn: () => api.get<Paginated<Trip>>(`trips/?driver=${id}&ordering=-requested_at&page_size=8`) });
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [reason, setReason] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["drivers"] });
  const suspend = useMutation({
    mutationFn: () => api.post(`drivers/${id}/suspend/`, { reason }),
    onSuccess: () => {
      toast.success("Driver suspended");
      setSuspendOpen(false);
      refresh();
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const reinstate = useMutation({ mutationFn: () => api.post(`drivers/${id}/reinstate/`), onSuccess: () => { toast.success("Driver reinstated"); refresh(); }, onError: (err) => toast.error((err as Error).message) });

  const d = driver.data;
  if (!d) return <Spinner className="mx-auto mt-20 size-7" />;
  return (
    <>
      <Link to="/ops/drivers" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" /> Drivers
      </Link>
      <div className="mb-6 flex flex-wrap items-center gap-4">
        <Avatar name={d.name} size={56} />
        <div className="flex-1">
          <h1 className="text-2xl font-bold tracking-tight">{d.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusBadge status={d.onboarding_status} /> <StatusBadge status={d.availability} /> {d.email} · {d.phone} · {d.city}
          </div>
        </div>
        {can("drivers.manage") &&
          (d.onboarding_status === "SUSPENDED" ? (
            <Button variant="outline" icon={<RotateCcw className="size-4" />} onClick={() => reinstate.mutate()} loading={reinstate.isPending}>
              Reinstate
            </Button>
          ) : (
            <Button variant="danger" icon={<Ban className="size-4" />} onClick={() => setSuspendOpen(true)}>
              Suspend
            </Button>
          ))}
      </div>

      {d.compliance_problems.length > 0 && (
        <div className="mb-4 flex gap-3 rounded-2xl border border-amber-300/50 bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
          <AlertTriangle className="size-5 shrink-0" />
          <div>
            <div className="font-semibold">Can't go online</div>
            <ul className="mt-1 list-disc pl-5">
              {d.compliance_problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Rating" value={Number(d.rating).toFixed(2)} sub={`${d.rating_count} ratings`} />
        <Stat label="Acceptance" value={`${Number(d.acceptance_rate).toFixed(0)}%`} sub="last 50 offers" />
        <Stat label="Safety score" value={d.safety_score ?? "—"} sub="telemetry-based" />
        <Stat label="Trips" value={d.completed_trips} sub={`${d.cancelled_trips} cancelled`} />
        <Stat label="Wallet" value={inr(d.wallet_balance, { whole: true })} sub={Number(d.wallet_balance) < 0 ? "dues owed" : "pending payout"} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Vehicle & licence" />
            <div className="px-5 py-3">
              {d.vehicle && (
                <div className="mb-2 flex items-center gap-3">
                  <RideTypeArt code={d.vehicle.ride_type} className="h-10 w-18" />
                  <div>
                    <div className="font-semibold">
                      {d.vehicle.make} {d.vehicle.model}
                    </div>
                    <div className="text-xs text-muted">
                      {d.vehicle.color} · {d.vehicle.year} · <span className="font-mono">{d.vehicle.registration_display}</span>
                    </div>
                  </div>
                </div>
              )}
              <KeyValue label="Licence">{d.license_number}</KeyValue>
              <KeyValue label="Licence expiry">{date(d.license_expiry)}</KeyValue>
              <KeyValue label="Approved">{date(d.approved_at)}</KeyValue>
              <KeyValue label="Last GPS">{ago(d.location_updated_at)}</KeyValue>
            </div>
          </Card>
          {d.current_lat !== null && d.current_lng !== null && (
            <Card className="h-56 overflow-hidden">
              <BaseMap center={[d.current_lat, d.current_lng]} zoom={14}>
                <CarMarker lat={d.current_lat} lng={d.current_lng} rideType={d.vehicle?.ride_type} />
              </BaseMap>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Documents" subtitle="Approve every required document to activate the driver" />
            <div className="divide-y divide-line">
              {(docs.data ?? []).map((doc) => (
                <DocumentRow key={doc.id} doc={doc} />
              ))}
              {docs.data?.length === 0 && <p className="px-5 py-6 text-center text-sm text-muted">No documents uploaded.</p>}
            </div>
          </Card>
          <Card>
            <CardHeader title="Recent trips" />
            <Table>
              <thead>
                <tr>
                  <Th>Trip</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Fare</Th>
                </tr>
              </thead>
              <tbody>
                {trips.data?.results.map((t) => (
                  <tr key={t.id}>
                    <Td>
                      <Link to={`/ops/trips/${t.id}`} className="font-medium hover:underline">
                        {t.trip_number}
                      </Link>
                      <div className="text-xs text-muted">{dateTime(t.requested_at)}</div>
                    </Td>
                    <Td>
                      <StatusBadge status={t.status} />
                    </Td>
                    <Td className="text-right">{inr(t.fare_total ?? t.estimated_fare)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      </div>

      <Modal
        open={suspendOpen}
        onClose={() => setSuspendOpen(false)}
        title={`Suspend ${d.name}?`}
        footer={
          <Button variant="danger" onClick={() => suspend.mutate()} disabled={!reason.trim()} loading={suspend.isPending}>
            Suspend driver
          </Button>
        }
      >
        <p className="mb-3 text-sm text-muted">The driver goes offline immediately and can't receive trips until reinstated. They'll be told the reason.</p>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" />
      </Modal>
    </>
  );
}
