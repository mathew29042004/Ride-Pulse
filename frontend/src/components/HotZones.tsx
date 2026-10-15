/** Driver app: zones near you expected to be busy in the next hour (from the demand forecast). */

import { useQuery } from "@tanstack/react-query";
import { Flame } from "lucide-react";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface HotZone {
  zone_id: number;
  zone: string;
  expected_trips: number;
  drivers_nearby: number;
  distance_km: number;
  status: "SHORT" | "TIGHT" | "OK";
}

export function HotZones() {
  const zones = useQuery({ queryKey: ["driver", "hot-zones"], queryFn: () => api.get<HotZone[]>("intel/hot_zones/"), refetchInterval: 120_000 });
  const list = (zones.data ?? []).filter((z) => z.status !== "OK");
  if (!list.length) return null;
  return (
    <div className="mb-3 rounded-2xl bg-surface-2 p-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-muted">
        <Flame className="size-3.5 text-orange-500" /> {t("Busy in the next hour")}
      </div>
      {list.map((z) => (
        <div key={z.zone_id} className="flex items-center justify-between py-1 text-sm">
          <span className="font-semibold">{z.zone}</span>
          <span className="text-xs text-muted">
            {t("~{n} trips · {km} km away", { n: Math.round(z.expected_trips), km: z.distance_km })}
          </span>
        </div>
      ))}
    </div>
  );
}
