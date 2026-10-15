/** "You're offline" strip: the app keeps working and shows what will be sent on reconnect. */

import { CloudOff, RefreshCw } from "lucide-react";

import { t } from "@/lib/i18n";
import { flush, useOnline, useQueued } from "@/lib/offline";

export function OfflineBanner() {
  const online = useOnline();
  const queued = useQueued();
  if (online && !queued) return null;
  return (
    <div role="status" className="relative z-[1100] flex items-center justify-center gap-2 bg-amber-500 px-3 py-1.5 text-xs font-semibold text-amber-950">
      {online ? <RefreshCw className="size-3.5 animate-spin" /> : <CloudOff className="size-3.5" />}
      {online
        ? t("Back online · sending {n} saved updates…", { n: queued })
        : queued
          ? t("You're offline · {n} updates saved on this phone, they'll send when you're back", { n: queued })
          : t("You're offline · showing the last saved information")}
      {online && queued > 0 && (
        <button onClick={() => void flush()} className="underline">
          {t("Retry")}
        </button>
      )}
    </div>
  );
}
