/** Call the other party through Ride Pulse's masked number: neither side sees the other's. */

import { useMutation } from "@tanstack/react-query";
import { Phone, PhoneCall, ShieldCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { Avatar, Button } from "@/components/ui";
import { t } from "@/lib/i18n";
import { api, ApiError } from "@/lib/api";

export function CallButton({ tripId, name, compact = false }: { tripId: number; name: string; compact?: boolean }) {
  const [result, setResult] = useState<{ mode: string; message: string } | null>(null);
  const call = useMutation({
    mutationFn: () => api.post<{ mode: string; message: string }>(`trips/${tripId}/call/`),
    onSuccess: setResult,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't place the call.")),
  });

  return (
    <>
      {compact ? (
        <button onClick={() => call.mutate()} disabled={call.isPending} className="flex size-10 items-center justify-center rounded-full bg-surface-3" aria-label={t("Call {name}", { name })}>
          <Phone className="size-4" />
        </button>
      ) : (
        <button onClick={() => call.mutate()} disabled={call.isPending} className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 py-3 text-xs font-semibold">
          <Phone className="size-4" /> {t("Call")}
        </button>
      )}
      {createPortal(
        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 z-[890] flex flex-col items-center justify-center gap-5 bg-[#070a10]/95 p-8 text-center text-white"
              role="dialog"
              aria-label={t("Calling {name}", { name })}
            >
              <div className="relative">
                <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400/30" />
                <Avatar name={name} size={88} />
              </div>
              <div>
                <div className="text-xl font-bold">{name}</div>
                <div className="mt-1 flex items-center justify-center gap-1.5 text-sm text-white/70">
                  <PhoneCall className="size-4" /> {result.mode === "exotel" ? t("Connecting…") : t("Demo call")}
                </div>
              </div>
              <p className="max-w-xs text-sm text-white/80">{result.message}</p>
              <p className="flex items-center gap-1.5 text-xs text-white/60">
                <ShieldCheck className="size-4" /> {t("Your number stays private")}
              </p>
              <Button variant="danger" size="lg" onClick={() => setResult(null)} className="mt-4 rounded-full px-8">
                {t("Close")}
              </Button>
            </motion.div>
          )}
        </AnimatePresence>,
        document.getElementById("phone-screen") ?? document.body,
      )}
    </>
  );
}
