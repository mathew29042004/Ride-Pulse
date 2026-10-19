/** Ops → Booking counter: book a ride for a walk-up passenger at a station who pays cash, print
 * the slip with their Ride PIN, and see today's bookings and cash for the drawer. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PlacePick, type Picked } from "@/components/PlacePick";
import { Badge, Button, Card, CardHeader, Field, Input, PageHeader, Select, Stat } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";

interface Slip {
  id: number;
  trip_number: string;
  passenger: string;
  phone: string;
  pin: string;
  from: string;
  to: string;
  ride_type: string;
  cash: string;
  status_label: string;
  driver: string | null;
  vehicle: string | null;
  booked_by: string;
  created_at: string;
}
interface CounterData {
  id: number;
  name: string;
  city: string;
  summary: { bookings: number; cash: string; by_staff: { name: string; bookings: number; cash: string }[] };
  bookings: Slip[];
}

export default function OpsCounter() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["counters"], queryFn: () => api.get<{ id: number; name: string; city: string }[]>("counters/") });
  const [id, setId] = useState<number | null>(null);
  const counterId = id ?? list.data?.[0]?.id ?? null;
  const q = useQuery({ queryKey: ["counter", counterId], queryFn: () => api.get<CounterData>(`counters/${counterId}/`), enabled: counterId != null, refetchInterval: 15_000 });
  const [to, setTo] = useState<Picked | null>(null);
  const [rideType, setRideType] = useState("AUTO");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [printed, setPrinted] = useState<Slip | null>(null);
  const book = useMutation({
    mutationFn: () => api.post<Slip>(`counters/${counterId}/book/`, { ride_type: rideType, dropoff: { lat: to!.lat, lng: to!.lng, address: to!.name }, passenger_name: name, passenger_phone: phone }),
    onSuccess: (s) => { setPrinted(s); setName(""); setPhone(""); setTo(null); qc.invalidateQueries({ queryKey: ["counter", counterId] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't book."),
  });
  const d = q.data;
  return (
    <>
      <PageHeader title="Booking counter" subtitle="For passengers without a smartphone: book, take the fare in cash, print the slip with their Ride PIN." actions={
        <Select value={counterId ?? ""} onChange={(e) => setId(Number(e.target.value))} aria-label="Counter" className="!w-72 !py-2">
          {list.data?.map((c) => <option key={c.id} value={c.id}>{c.city} · {c.name}</option>)}
        </Select>
      } />
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <Card className="space-y-3 p-4">
          <CardHeader title="New booking" />
          <Field label="Where to?"><PlacePick value={to} onChange={setTo} placeholder="Search the destination" /></Field>
          <Field label="Ride type">
            <Select value={rideType} onChange={(e) => setRideType(e.target.value)}>
              {["AUTO", "MINI", "SEDAN", "SUV"].map((r) => <option key={r}>{r}</option>)}
            </Select>
          </Field>
          <Field label="Passenger name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Mobile (optional, for SMS)"><Input inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
          <Button block disabled={!to || name.trim().length < 2} loading={book.isPending} onClick={() => book.mutate()}>Take cash and book</Button>
        </Card>
        <div className="space-y-4">
          {printed && (
            <Card className="p-4 print:shadow-none" id="slip">
              <CardHeader title="Slip" action={<Button size="sm" variant="secondary" onClick={() => window.print()}>Print</Button>} />
              <div className="text-sm">
                <div className="text-2xl font-bold">PIN {printed.pin}</div>
                <div>{printed.passenger} · {printed.ride_type} · paid {inr(printed.cash)} cash</div>
                <div>{printed.from} → {printed.to}</div>
                <div className="text-xs text-muted">{printed.trip_number} · {dateTime(printed.created_at)} · tell the driver the PIN to start</div>
              </div>
            </Card>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Card className="p-3"><Stat label="Bookings today" value={d?.summary.bookings ?? "—"} /></Card>
            <Card className="p-3"><Stat label="Cash in drawer" value={inr(d?.summary.cash ?? 0)} sub={d?.summary.by_staff.map((s) => `${s.name}: ${inr(s.cash)}`).join(" · ")} /></Card>
          </div>
          <Card className="p-4">
            <CardHeader title="Today" />
            {d && !d.bookings.length && <p className="text-sm text-muted">No bookings yet today.</p>}
            {d?.bookings.map((b) => (
              <div key={b.id} className="flex items-center justify-between border-b border-line py-2 text-sm last:border-0">
                <span>{b.passenger} → {b.to} <span className="text-xs text-muted">PIN {b.pin} · {inr(b.cash)}{b.vehicle ? ` · ${b.driver} ${b.vehicle}` : ""}</span></span>
                <Badge tone="neutral">{b.status_label}</Badge>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  );
}
