import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Clock, Home, LifeBuoy } from "lucide-react";
import { Link } from "react-router";
import { toast } from "sonner";

import { TrustLinks } from "@/components/TrustLinks";
import { VehicleCare } from "@/components/DriverBusiness";
import { useMapProvider } from "@/components/map";
import { describePoint } from "@/components/PlaceSuggestions";
import { PushToggle } from "@/components/PushToggle";
import { Avatar, Button, Stars } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { useDriverMe } from "@/lib/hooks";
import type { Driver } from "@/lib/types";

import { LanguageRow, LogoutRow, ThemeRow } from "../rider/RiderAccount";

function Meter({ label, value, max = 100, suffix = "", good = 80 }: { label: string; value: number | null; max?: number; suffix?: string; good?: number }) {
  const pct = value === null ? 0 : Math.min(100, (value / max) * 100);
  const tone = value === null ? "bg-surface-3" : value >= good ? "bg-brand" : value >= good * 0.75 ? "bg-amber-500" : "bg-danger";
  return (
    <div className="rounded-2xl bg-surface-2 p-3">
      <div className="text-[11px] font-semibold text-muted uppercase">{label}</div>
      <div className="mt-0.5 text-xl font-bold">{value === null ? "—" : `${value}${suffix}`}</div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function DriverAccount() {
  const me = useDriverMe(false);
  const d = me.data;
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <div className="flex items-center gap-4">
        <Avatar name={d?.name ?? "Driver"} size={64} />
        <div>
          <h1 className="text-xl font-bold">{d?.name}</h1>
          <div className="text-sm text-muted">
            <Stars value={d?.rating ?? 5} /> · {d?.rating_count ?? 0} ratings
          </div>
          <div className="text-xs text-muted">Driving since {date(d?.approved_at ?? null)}</div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2">
        <Meter label="Acceptance" value={d ? Math.round(Number(d.acceptance_rate)) : null} suffix="%" good={85} />
        <Meter label="Safety score" value={d?.safety_score ?? null} good={80} />
        <Meter label="Rating" value={d ? Number(d.rating) : null} max={5} good={4.6} />
        <Meter label="Trips" value={d?.completed_trips ?? null} max={Math.max(100, d?.completed_trips ?? 0)} good={0} />
      </div>
      <p className="mt-2 text-xs text-muted">The safety score comes from braking, acceleration, speeding and night driving on your recent trips. Safer drivers rank higher in dispatch.</p>

      <Link to="/drive/academy" className="mt-4 flex items-center justify-between rounded-3xl border border-line p-4 text-sm font-semibold">
        Driver Academy: courses and certificates <span aria-hidden>→</span>
      </Link>
      <VehicleCare />

      <div className="mt-6 divide-y divide-line">
        <PushToggle audience="driver" />
        {d && <HomeRow driver={d} />}
        <TrustLinks base="/drive" />
        <Link to="/drive/support" className="flex items-center gap-3 py-3.5">
          <LifeBuoy className="size-5" />
          <span className="flex-1 font-medium">Help & support</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
        <div className="flex items-center gap-3 py-3.5">
          <Clock className="size-5" />
          <span className="flex-1 font-medium">Licence expires</span>
          <span className="text-sm text-muted">{date(d?.license_expiry ?? null)}</span>
        </div>
        <LanguageRow />
        <ThemeRow />
        <LogoutRow />
      </div>
    </div>
  );
}

/** Home location for going-home mode: set to where the car is now. */
function HomeRow({ driver }: { driver: Driver }) {
  const qc = useQueryClient();
  const { provider } = useMapProvider();
  const save = useMutation({
    mutationFn: async () => {
      if (driver.current_lat === null || driver.current_lng === null) throw new Error("Go online first so we know where you are.");
      const address = await describePoint(driver.current_lat, driver.current_lng, provider);
      return api.post<Driver>("driver/home/", { lat: driver.current_lat, lng: driver.current_lng, address });
    },
    onSuccess: (updated) => {
      qc.setQueryData(["driver", "me"], updated);
      toast.success(`Home set to ${updated.home_address}`);
    },
    onError: (err) => toast.error((err as Error).message),
  });
  return (
    <div className="flex items-center gap-3 py-3.5">
      <Home className="size-5" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">Home (for going-home mode)</div>
        <div className="truncate text-xs text-muted">{driver.home_address || "Not set"}</div>
      </div>
      <Button size="sm" variant="outline" loading={save.isPending} onClick={() => save.mutate()}>
        Set to here
      </Button>
    </div>
  );
}
