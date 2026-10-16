/** After a completed ride: tell us something was wrong with the car (AC, cleanliness, belts).
 * The driver and their fleet owner are told; the car stays on the road. */

import { useMutation } from "@tanstack/react-query";
import { CarFront } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Modal, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

const KINDS = [
  ["AC", "AC wasn't working"],
  ["CLEANLINESS", "Car wasn't clean"],
  ["SEATBELTS", "Seat belt didn't work"],
  ["OTHER", "Something else"],
] as const;

export function ReportCar({ trip }: { trip: Trip }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [kind, setKind] = useState<string>("AC");
  const [description, setDescription] = useState("");
  const send = useMutation({
    mutationFn: () => api.post(`trips/${trip.id}/vehicle-issue/`, { kind, description }),
    onSuccess: () => {
      setOpen(false);
      setSent(true);
      toast.success(t("Thanks. We've told the driver and we'll check the car."));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Something went wrong.")),
  });
  if (trip.status !== "COMPLETED") return null;
  return (
    <>
      <button disabled={sent} onClick={() => setOpen(true)} className="mt-3 flex w-full items-center gap-2 rounded-2xl border border-line px-4 py-3 text-left text-sm disabled:opacity-60">
        <CarFront className="size-4 text-muted" />
        {sent ? t("Car problem reported") : t("Something wrong with the car?")}
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title={t("Report the car")}>
        <div className="space-y-2">
          {KINDS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="radio" name="car-issue" checked={kind === k} onChange={() => setKind(k)} />
              {t(label)}
            </label>
          ))}
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t("Anything else we should know? (optional)")} rows={3} />
          <Button block loading={send.isPending} onClick={() => send.mutate()}>
            {t("Send")}
          </Button>
        </div>
      </Modal>
    </>
  );
}
