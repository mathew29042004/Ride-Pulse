/** Record trip audio for safety (encrypted, kept on this device) and send it to the safety team. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Mic, Send, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, ApiError, request } from "@/lib/api";
import { useNow } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { deleteOldRecordings, listRecordings, shareRecording, startRecording, type StoredRecording } from "@/lib/recorder";
import type { Trip } from "@/lib/types";

const RECORDABLE = new Set(["DRIVER_ASSIGNED", "DRIVER_ARRIVED", "IN_PROGRESS"]);
const supported = typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices && "indexedDB" in window;

export function TripRecorder({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const stopRef = useRef<null | (() => Promise<StoredRecording>)>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const now = useNow(1000);
  const key = ["recordings", trip.id];
  const saved = useQuery({ queryKey: key, queryFn: () => listRecordings(trip.id), enabled: supported });

  useEffect(() => {
    if (supported) deleteOldRecordings().catch(() => undefined);
    return () => {
      stopRef.current?.().catch(() => undefined); // leaving the screen ends the recording safely
    };
  }, []);

  if (!supported) return null;
  const canRecord = RECORDABLE.has(trip.status);
  const pending = (saved.data ?? []).filter((r) => !r.shared);
  if (!canRecord && !pending.length) return null;

  const start = async () => {
    setBusy(true);
    try {
      stopRef.current = await startRecording(trip.id);
      setStartedAt(Date.now());
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : t("Couldn't use the microphone."));
    } finally {
      setBusy(false);
    }
  };
  const stop = async () => {
    setBusy(true);
    try {
      await stopRef.current?.();
      stopRef.current = null;
      setStartedAt(null);
      qc.invalidateQueries({ queryKey: key });
      toast.success(t("Recording saved on this phone (deleted after 7 days)."));
    } finally {
      setBusy(false);
    }
  };
  const share = async (recording: StoredRecording) => {
    setBusy(true);
    try {
      const { ticket_number } = await shareRecording(recording);
      qc.invalidateQueries({ queryKey: key });
      toast.success(t("Sent to the safety team ({ticket}). They'll contact you.", { ticket: ticket_number }));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : t("Couldn't send the recording."));
    } finally {
      setBusy(false);
    }
  };
  const seconds = startedAt ? Math.floor((now - startedAt) / 1000) : 0;

  return (
    <div className="mt-3 rounded-2xl bg-surface-2 px-3 py-2.5 text-sm">
      {canRecord && (
        <button onClick={startedAt ? stop : start} disabled={busy} className="flex w-full items-center gap-2 text-left">
          <span className={clsx("flex size-8 items-center justify-center rounded-full", startedAt ? "bg-danger text-white" : "bg-surface-3")}>
            {startedAt ? <Square className="size-3.5" /> : <Mic className="size-4" />}
          </span>
          <span className="flex-1">
            <span className="block font-semibold">{startedAt ? t("Recording… {time}", { time: `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` }) : t("Record audio for safety")}</span>
            <span className="block text-[11px] text-muted">{t("Encrypted and kept on this phone. Shared only if you report a problem.")}</span>
          </span>
        </button>
      )}
      {pending.map((r) => (
        <div key={r.id} className="mt-2 flex items-center gap-2 border-t border-line pt-2 text-xs">
          <Mic className="size-3.5 text-muted" />
          <span className="flex-1">{t("Recording · {n}s", { n: r.seconds })}</span>
          <button onClick={() => share(r)} disabled={busy} className="flex items-center gap-1 font-semibold text-danger">
            <Send className="size-3.5" /> {t("Send to safety team")}
          </button>
        </div>
      ))}
    </div>
  );
}

interface SafetyRecordingRow {
  id: number;
  trip_number: string;
  uploaded_by_name: string;
  duration_seconds: number;
  created_at: string;
}

/** Ops: recordings shared for a ticket, played on demand (each playback is audited). */
export function SafetyRecordings({ ticketId }: { ticketId: number }) {
  const rows = useQuery({
    queryKey: ["safety", "recordings", ticketId],
    queryFn: () => api.get<{ results: SafetyRecordingRow[] }>(`safety/recordings/?ticket=${ticketId}`),
  });
  const [urls, setUrls] = useState<Record<number, string>>({});
  if (!rows.data?.results.length) return null;
  const play = async (id: number) => {
    try {
      // Through the API client: this tab's sign-in, token refresh, and the audit on the server.
      const response = await request<Response>(`/api/v1/safety/recordings/${id}/audio/`, { raw: true });
      const url = URL.createObjectURL(await response.blob());
      setUrls((u) => ({ ...u, [id]: url }));
    } catch {
      toast.error("Couldn't load the recording.");
    }
  };
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Mic className="size-4" /> Audio recordings
      </div>
      {rows.data.results.map((r) => (
        <div key={r.id} className="flex flex-wrap items-center gap-3 py-1.5 text-sm">
          <span className="flex-1">
            {r.uploaded_by_name} · {r.duration_seconds}s · {r.trip_number}
          </span>
          {urls[r.id] ? (
            <audio controls src={urls[r.id]} className="h-8" autoPlay />
          ) : (
            <button onClick={() => play(r.id)} className="rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold">
              Play (logged)
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
