/** Shared ride: tells the rider (or driver) that one more rider is on this run. */

import { Users } from "lucide-react";

import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

export function PoolBadge({ trip, role }: { trip: Trip; role: "rider" | "driver" }) {
  if (!trip.pool_id) return null;
  const text =
    role === "driver"
      ? trip.co_riders
        ? t("Shared ride · {n} more rider on this run. Pickups first, then drop-offs.", { n: trip.co_riders })
        : t("Shared ride · last rider on this run")
      : trip.co_riders
        ? t("Sharing with {n} co-rider · your driver may make one extra stop", { n: trip.co_riders })
        : t("Shared ride");
  return (
    <div className="mt-3 flex items-center gap-2 rounded-2xl bg-surface-2 px-3 py-2.5 text-sm">
      <Users className="size-4 shrink-0 text-brand-strong" />
      <span>{text}</span>
    </div>
  );
}
