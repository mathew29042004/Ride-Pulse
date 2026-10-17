/** "How likely are you to recommend Ride Pulse?" Shown at most every 90 days, after a few trips. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

export function NpsCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["nps", "prompt"], queryFn: () => api.get<{ ask: boolean }>("nps/prompt/"), staleTime: 600_000 });
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const done = () => qc.setQueryData(["nps", "prompt"], { ask: false });
  const send = useMutation({
    mutationFn: () => api.post("nps/answer/", { score, comment }),
    onSuccess: () => {
      done();
      toast.success(t("Thank you for telling us!"));
    },
  });
  const later = useMutation({ mutationFn: () => api.post("nps/snooze/"), onSuccess: done });
  if (!q.data?.ask) return null;
  return (
    <div className="mb-3 rounded-2xl border border-line p-3 text-sm">
      <div className="font-semibold">{t("How likely are you to recommend Ride Pulse to a friend?")}</div>
      <div className="mt-2 grid grid-cols-11 gap-1">
        {Array.from({ length: 11 }, (_, n) => (
          <button key={n} onClick={() => setScore(n)} className={clsx("rounded-lg py-1.5 text-xs font-semibold", score === n ? "bg-ink text-ink-fg" : "bg-surface-2")}>
            {n}
          </button>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted">
        <span>{t("Not likely")}</span>
        <span>{t("Very likely")}</span>
      </div>
      {score !== null && (
        <>
          <Input className="mt-2" value={comment} onChange={(e) => setComment(e.target.value)} placeholder={score >= 9 ? t("What do you like most? (optional)") : t("What should we do better? (optional)")} />
          <Button className="mt-2" block size="sm" loading={send.isPending} onClick={() => send.mutate()}>
            {t("Send")}
          </Button>
        </>
      )}
      <button onClick={() => later.mutate()} className="mt-2 w-full text-center text-xs text-muted">
        {t("Not now")}
      </button>
    </div>
  );
}
