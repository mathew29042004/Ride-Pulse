/** Ops → Monsoon mode: turn on heavy-rain or flood mode for a city. Rain caps surge at 1.5x;
 * a flood removes surge, pauses bike taxis and closes the flooded zones you tick. Riders and
 * drivers in the city see a banner; drivers get a safety notice. It ends by itself. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudRain } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, EmptyState, Field, Input, PageHeader, Segmented, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";

interface Alert {
  id: number;
  city: string;
  level: "RAIN" | "FLOOD";
  level_label: string;
  zones: string[];
  message: string;
  starts_at: string;
  ends_at: string;
  active: boolean;
  by: string | null;
}
interface Data {
  alerts: Alert[];
  cities: { id: number; name: string; zones: { id: number; name: string }[] }[];
}

export default function OpsWeather() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "weather"], queryFn: () => api.get<Data>("ops/weather/") });
  const [city, setCity] = useState<number | null>(null);
  const [level, setLevel] = useState<"RAIN" | "FLOOD">("RAIN");
  const [hours, setHours] = useState(6);
  const [zones, setZones] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "weather"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const start = useMutation({
    mutationFn: () => api.post("ops/weather/", { city, level, hours, zones, message }),
    onSuccess: () => {
      toast.success("Turned on. Drivers in the city have been told.");
      setZones([]);
      setMessage("");
      refresh();
    },
    onError: fail,
  });
  const end = useMutation({ mutationFn: (id: number) => api.post(`ops/weather/${id}/end/`), onSuccess: refresh, onError: fail });
  const chosen = q.data?.cities.find((c) => c.id === city);
  return (
    <>
      <PageHeader title="Monsoon mode" subtitle="Heavy rain caps surge at 1.5x. Flooding removes surge, pauses bike taxis and closes the zones you tick. Riders and drivers in the city see a banner. It ends by itself." />
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card className="space-y-3 p-4">
          <Field label="City">
            <Select value={city ?? ""} onChange={(e) => { setCity(Number(e.target.value) || null); setZones([]); }}>
              <option value="">Choose…</option>
              {q.data?.cities.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </Field>
          <Segmented value={level} onChange={setLevel} options={[{ value: "RAIN", label: "Heavy rain" }, { value: "FLOOD", label: "Flooding" }]} />
          {level === "FLOOD" && chosen && (
            <Field label="Flooded zones (no pick-ups or drops)">
              <div className="flex max-h-40 flex-wrap gap-1 overflow-auto">
                {chosen.zones.map((z) => {
                  const on = zones.includes(z.id);
                  return (
                    <button key={z.id} onClick={() => setZones(on ? zones.filter((x) => x !== z.id) : [...zones, z.id])} className={`rounded-full px-2 py-1 text-xs ${on ? "bg-danger text-white" : "bg-surface-2"}`}>
                      {z.name}
                    </button>
                  );
                })}
              </div>
            </Field>
          )}
          <Field label="For how many hours">
            <Input type="number" min={1} max={72} value={hours} onChange={(e) => setHours(Number(e.target.value))} />
          </Field>
          <Field label="Message (optional)" hint="Shown to riders and drivers. Leave blank for the standard one.">
            <Input value={message} onChange={(e) => setMessage(e.target.value)} maxLength={240} />
          </Field>
          <Button block disabled={!city} loading={start.isPending} onClick={() => start.mutate()}>
            Turn on
          </Button>
        </Card>
        <div className="space-y-2">
          {q.data && !q.data.alerts.length && <EmptyState icon={<CloudRain />} title="No weather alerts yet" />}
          {q.data?.alerts.map((a) => (
            <Card key={a.id} className="flex items-start justify-between gap-3 p-3 text-sm">
              <div>
                <div className="flex items-center gap-2 font-semibold">
                  {a.city} <Badge tone={a.level === "FLOOD" ? "danger" : "warning"}>{a.level_label}</Badge>
                  {a.active ? <Badge tone="brand">On</Badge> : <Badge tone="neutral">Ended</Badge>}
                </div>
                <div className="mt-1 text-muted">{a.message}</div>
                {a.zones.length > 0 && <div className="mt-1 text-xs">Closed: {a.zones.join(", ")}</div>}
                <div className="mt-1 text-xs text-muted">
                  {dateTime(a.starts_at)} → {dateTime(a.ends_at)}{a.by ? ` · ${a.by}` : ""}
                </div>
              </div>
              {a.active && (
                <Button size="sm" variant="secondary" loading={end.isPending} onClick={() => end.mutate(a.id)}>
                  End now
                </Button>
              )}
            </Card>
          ))}
        </div>
      </div>
    </>
  );
}
