/**
 * Rider side of pickup verification: "Is this your car?" with the plate in big letters, then
 * the rotating QR code the driver scans (with the 4-digit PIN as a fallback: tap to reveal,
 * or let the phone read it out).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CheckCircle2, Eye, QrCode, ShieldAlert, Volume2 } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Trip } from "@/lib/types";

/** "Maruti Suzuki Swift · TN 09 AB 1234" -> model and plate. */
function splitVehicle(vehicle: string | null): { model: string; plate: string } {
  const [model, plate] = (vehicle ?? "").split(" · ");
  return { model: model ?? "", plate: plate ?? "" };
}

export function CarCheck({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const { model, plate } = splitVehicle(trip.vehicle);
  const confirm = useMutation({
    mutationFn: (isMyCar: boolean) => api.post<Trip>(`trips/${trip.id}/confirm-car/`, { is_my_car: isMyCar }),
    onSuccess: (_, isMyCar) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      if (!isMyCar) toast.warning("Our safety team has been alerted and will call you. Don't get in.", { duration: 10_000 });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Something went wrong."),
  });
  if (!plate) return null;
  if (trip.car_confirmed_at) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-2xl bg-brand-soft px-4 py-2.5 text-sm font-semibold text-brand-strong dark:text-brand-fg">
        <CheckCircle2 className="size-4" /> Car confirmed: {plate}
      </div>
    );
  }
  return (
    <div className="mt-3 rounded-2xl border-2 border-dashed border-line p-4">
      <div className="text-xs font-semibold tracking-wide text-muted uppercase">Check before you get in</div>
      <div className="mt-2 flex items-center gap-3">
        <div className="shrink-0 rounded-lg border-2 border-fg bg-yellow-300 px-3 py-1 font-mono text-lg font-black tracking-wider whitespace-nowrap text-black">{plate}</div>
        <div className="min-w-0 text-sm text-muted">{model}</div>
      </div>
      <p className="mt-2 text-sm font-semibold">Is this your car?</p>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Button variant="outline" onClick={() => confirm.mutate(false)} disabled={confirm.isPending} icon={<ShieldAlert className="size-4" />}>
          No
        </Button>
        <Button variant="brand" onClick={() => confirm.mutate(true)} loading={confirm.isPending && confirm.variables} icon={<CheckCircle2 className="size-4" />}>
          Yes
        </Button>
      </div>
    </div>
  );
}

export function StartCode({ trip }: { trip: Trip }) {
  const [mode, setMode] = useState<"qr" | "pin">("qr");
  const [revealed, setRevealed] = useState(false);
  const [svg, setSvg] = useState("");
  const code = useQuery({
    queryKey: ["trips", String(trip.id), "start-code"],
    queryFn: () => api.get<{ code: string; expires_in: number }>(`trips/${trip.id}/start-code/`),
    enabled: mode === "qr" && !!trip.otp,
    // Refresh just as the code rotates (every 30 s).
    refetchInterval: (q) => Math.max(1, q.state.data?.expires_in ?? 30) * 1000,
  });
  useEffect(() => {
    if (!code.data) return;
    QRCode.toString(code.data.code, { type: "svg", margin: 1, errorCorrectionLevel: "M", color: { dark: "#0b0f19", light: "#ffffff" } }).then(setSvg);
  }, [code.data?.code]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!trip.otp) return null;
  const readAloud = () => {
    const speech = new SpeechSynthesisUtterance(`Your ride PIN is ${trip.otp!.split("").join(", ")}`);
    speech.lang = "en-IN";
    speech.rate = 0.8;
    window.speechSynthesis?.cancel();
    window.speechSynthesis?.speak(speech);
  };

  return (
    <div className="mt-3 rounded-2xl bg-surface-2 p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">{mode === "qr" ? "Show this to your driver" : "Tell your driver this PIN"}</div>
        <div className="flex rounded-full bg-surface-3 p-0.5 text-xs font-semibold" role="tablist">
          {(["qr", "pin"] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)} className={clsx("rounded-full px-3 py-1", mode === m && "bg-surface shadow-sm")}>
              {m === "qr" ? "QR" : "PIN"}
            </button>
          ))}
        </div>
      </div>
      {mode === "qr" ? (
        <div className="mt-3 flex flex-col items-center gap-2">
          {svg ? (
            <div className="size-44 rounded-xl bg-white p-2" aria-label="Ride start QR code" role="img" dangerouslySetInnerHTML={{ __html: svg }} />
          ) : (
            <div className="flex size-44 items-center justify-center rounded-xl bg-surface-3">
              <QrCode className="size-8 text-muted" />
            </div>
          )}
          <p className="text-center text-xs text-muted">Changes every 30 seconds, so a photo of it won't work later.</p>
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => setRevealed((r) => !r)}
            className="flex-1 rounded-xl bg-ink py-3 text-center font-mono text-3xl font-bold tracking-[0.4em] text-ink-fg"
            aria-label={revealed ? "Hide PIN" : "Show PIN"}
          >
            {revealed ? trip.otp : "••••"}
          </button>
          <div className="flex flex-col gap-2">
            <button onClick={() => setRevealed((r) => !r)} className="flex size-10 items-center justify-center rounded-full bg-surface-3" aria-label="Show PIN">
              <Eye className="size-4" />
            </button>
            {"speechSynthesis" in window && (
              <button onClick={readAloud} className="flex size-10 items-center justify-center rounded-full bg-surface-3" aria-label="Read PIN aloud">
                <Volume2 className="size-4" />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
