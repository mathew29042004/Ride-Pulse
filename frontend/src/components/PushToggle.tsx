/** "Notifications on this device" switch (Web Push), for the Account screens and the driver home. */

import { useQuery } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { configQuery } from "@/components/map";
import { Button } from "@/components/ui";
import { disablePush, enablePush, pushStatus, type PushStatus } from "@/lib/push";
import { t } from "@/lib/i18n";

export function usePush() {
  const config = useQuery(configQuery);
  const key = config.data?.push?.vapid_public_key;
  const [status, setStatus] = useState<PushStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (config.data) pushStatus(key).then(setStatus);
  }, [config.data, key]);
  const toggle = async () => {
    if (!key) return;
    setBusy(true);
    try {
      if (status === "on") {
        await disablePush();
        setStatus("off");
      } else {
        await enablePush(key);
        setStatus("on");
        toast.success(t("Notifications are on for this device"));
      }
    } catch (err) {
      toast.error((err as Error).message);
      setStatus(await pushStatus(key));
    } finally {
      setBusy(false);
    }
  };
  return { status, busy, toggle };
}

export function PushToggle({ audience }: { audience: "rider" | "driver" }) {
  const { status, busy, toggle } = usePush();
  if (status === null || status === "disabled") return null;
  const detail =
    status === "unsupported"
      ? t("This browser can't receive push notifications. On iPhone, add Ride Pulse to your home screen first.") : status === "blocked"
        ? t("Blocked in your browser's site settings.") : audience === "driver"
          ? t("Get trip offers even when the app is in the background.") : "Know when your driver is assigned or has arrived, even with the app closed.";
  return (
    <div className="flex items-center gap-3 py-3">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-3">
        <BellRing className="size-[18px]" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{t("Push notifications")}</div>
        <div className="text-xs text-muted">{detail}</div>
      </div>
      {(status === "on" || status === "off") && (
        <Button size="sm" variant={status === "on" ? "outline" : "brand"} loading={busy} onClick={toggle}>
          {status === "on" ? t("Turn off") : t("Turn on")}
        </Button>
      )}
    </div>
  );
}
