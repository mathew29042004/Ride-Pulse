/**
 * Guardian mode (opt-in): if something goes wrong, the rider's live location goes to their
 * trusted contacts. Settings, the "you're sharing" banner (which keeps sending the phone's
 * location), shake-to-SOS, a fake incoming call, and one-tap 112.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Phone, PhoneOff, Radio, ShieldCheck, Siren, Vibrate } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";

export interface GuardianStatus {
  guardian_mode: boolean;
  fake_call_name: string;
  contacts: number;
  share: { id: number; triggers: string[]; started_at: string; contacts_alerted: number; link: string; last_at: string | null } | null;
}

const KEY = ["rider", "guardian"];
const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

export function useGuardian(poll = false) {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<GuardianStatus>("safety/guardian/status/"), refetchInterval: poll ? 20_000 : false });
}

export function currentPosition(): Promise<{ lat: number; lng: number } | null> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 30_000 },
    );
  });
}

// --- Settings (Account) ------------------------------------------------------------------------

export function GuardianSettings() {
  const qc = useQueryClient();
  const q = useGuardian();
  const [name, setName] = useState<string | null>(null);
  const [calling, setCalling] = useState(false);
  const save = useMutation({
    mutationFn: (body: Partial<Pick<GuardianStatus, "guardian_mode" | "fake_call_name">>) => api.post<GuardianStatus>("safety/guardian/settings/", body),
    onSuccess: (data) => {
      qc.setQueryData(KEY, data);
      setName(null);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const g = q.data;
  if (!g) return null;
  return (
    <div className="py-3.5">
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 size-5 text-brand" />
        <div className="flex-1">
          <div className="font-medium">{t("Guardian mode")}</div>
          <p className="text-xs text-muted">
            {t("If anything goes wrong (SOS, shaking your phone, an unusual stop or route), your trusted contacts get your live location right away, until you tap \"I'm safe\".")}
          </p>
        </div>
        <button
          role="switch"
          aria-checked={g.guardian_mode}
          aria-label={t("Guardian mode")}
          onClick={() => save.mutate({ guardian_mode: !g.guardian_mode })}
          className={clsx("relative h-6 w-11 shrink-0 rounded-full transition", g.guardian_mode ? "bg-brand" : "bg-surface-3")}
        >
          <span className={clsx("absolute top-0.5 size-5 rounded-full bg-white shadow transition", g.guardian_mode ? "left-[22px]" : "left-0.5")} />
        </button>
      </div>
      {!g.contacts && <p className="mt-2 pl-8 text-xs text-amber-700 dark:text-amber-400">{t("Add a trusted contact above to switch it on.")}</p>}
      <div className="mt-3 flex items-center gap-2 pl-8">
        <Input value={name ?? g.fake_call_name} onChange={(e) => setName(e.target.value)} placeholder={t("Fake call from")} className="!py-2 text-sm" aria-label={t("Fake call from")} />
        {name !== null && name.trim() && (
          <Button size="sm" variant="outline" onClick={() => save.mutate({ fake_call_name: name })}>
            {t("Save")}
          </Button>
        )}
        <Button size="sm" variant="ghost" icon={<Phone className="size-4" />} onClick={() => setCalling(true)}>
          {t("Try")}
        </Button>
      </div>
      <p className="mt-1 pl-8 text-[11px] text-muted">{t("A fake incoming call helps you leave an uncomfortable situation.")}</p>
      {calling && <FakeCall name={name ?? g.fake_call_name} onEnd={() => setCalling(false)} />}
    </div>
  );
}

// --- Banner while sharing (all rider screens) ----------------------------------------------------

export function GuardianBanner() {
  const qc = useQueryClient();
  const q = useGuardian(true);
  const share = q.data?.share;
  const safe = useMutation({
    mutationFn: () => api.post<GuardianStatus>("safety/guardian/safe/"),
    onSuccess: (data) => {
      qc.setQueryData(KEY, data);
      toast.success(t("Glad you're safe. Your contacts have been told."));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  // While sharing, send the phone's own location every 30 seconds (the car's is the fallback).
  useEffect(() => {
    if (!share || !("geolocation" in navigator)) return;
    let last = 0;
    const id = navigator.geolocation.watchPosition(
      (p) => {
        if (Date.now() - last < 30_000) return;
        last = Date.now();
        api.post("safety/guardian/location/", { lat: p.coords.latitude, lng: p.coords.longitude }).catch(() => undefined);
      },
      () => undefined,
      { enableHighAccuracy: true, maximumAge: 15_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [share?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!share) return null;
  return (
    <div className="sticky top-0 z-[700] flex items-center gap-2 bg-danger px-4 py-2 text-sm text-white">
      <Radio className="size-4 shrink-0 animate-pulse" />
      <span className="flex-1">{t("Sharing your live location with {n} trusted contacts", { n: share.contacts_alerted })}</span>
      <button onClick={() => safe.mutate()} className="rounded-full bg-white px-3 py-1 text-xs font-bold text-danger">
        {t("I'm safe")}
      </button>
    </div>
  );
}

// --- Shake to SOS --------------------------------------------------------------------------------

/** Three hard shakes within two seconds: a 5-second countdown the rider can cancel, then SOS. */
export function useShakeToSos(enabled: boolean, onTrigger: () => void) {
  const hits = useRef<number[]>([]);
  useEffect(() => {
    if (!enabled || typeof window === "undefined" || !("DeviceMotionEvent" in window)) return;
    const onMotion = (e: DeviceMotionEvent) => {
      const a = e.accelerationIncludingGravity;
      if (!a) return;
      const force = Math.sqrt((a.x ?? 0) ** 2 + (a.y ?? 0) ** 2 + (a.z ?? 0) ** 2);
      if (force < 28) return; // well above walking or a bumpy road (~10–18)
      const now = Date.now();
      hits.current = [...hits.current.filter((tm) => now - tm < 2000), now];
      if (hits.current.length >= 3) {
        hits.current = [];
        onTrigger();
      }
    };
    window.addEventListener("devicemotion", onMotion);
    return () => window.removeEventListener("devicemotion", onMotion);
  }, [enabled, onTrigger]);
}

export function ShakeCountdown({ onCancel, onFire }: { onCancel: () => void; onFire: () => void }) {
  const [left, setLeft] = useState(5);
  useEffect(() => {
    if (left <= 0) {
      onFire();
      return;
    }
    navigator.vibrate?.(200);
    const id = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(id);
  }, [left]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="fixed inset-0 z-[1100] flex flex-col items-center justify-center gap-6 bg-danger p-6 text-center text-white">
      <Vibrate className="size-12" />
      <div className="text-2xl font-bold">{t("Sending SOS in {n}", { n: left })}</div>
      <p className="max-w-xs text-sm opacity-90">{t("Our safety team will call you and your trusted contacts will see where you are.")}</p>
      <div className="flex gap-3">
        <button onClick={onFire} className="rounded-full bg-white px-6 py-3 font-bold text-danger">
          {t("Send now")}
        </button>
        <button onClick={onCancel} className="rounded-full border border-white px-6 py-3 font-bold">
          {t("Cancel")}
        </button>
      </div>
    </div>
  );
}

// --- On a trip: shake, share, 112, fake call -------------------------------------------------------

function useShare() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (trigger: "SHAKE" | "MANUAL") => api.post<GuardianStatus>("safety/guardian/share/", { trigger, ...((await currentPosition()) ?? {}) }),
    onSuccess: (data, trigger) => {
      qc.setQueryData(KEY, data);
      toast.success(trigger === "SHAKE" ? t("SOS sent. Help is on the way.") : t("Your live location is now shared with your trusted contacts."));
    },
    onError: (err) => toast.error(errorText(err)),
  });
}

/** Mounted for the whole trip screen: three hard shakes start the SOS countdown. */
export function ShakeToSos({ active }: { active: boolean }) {
  const g = useGuardian().data;
  const send = useShare();
  const [countdown, setCountdown] = useState(false);
  useShakeToSos(active && !!g?.guardian_mode, () => setCountdown(true));
  if (!countdown) return null;
  return (
    <ShakeCountdown
      onCancel={() => setCountdown(false)}
      onFire={() => {
        setCountdown(false);
        send.mutate("SHAKE");
      }}
    />
  );
}

/** In the SOS sheet: 112, share my location, fake call. */
export function TripGuardian({ active }: { active: boolean }) {
  const g = useGuardian().data;
  const send = useShare();
  const [calling, setCalling] = useState(false);
  if (!g) return null;
  return (
    <>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <a href="tel:112" className="flex flex-col items-center gap-1 rounded-2xl bg-danger/10 px-2 py-2.5 text-xs font-semibold text-danger">
          <Siren className="size-5" /> {t("Call 112")}
        </a>
        <button disabled={!g.contacts || !!g.share || send.isPending} onClick={() => send.mutate("MANUAL")} className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 px-2 py-2.5 text-xs font-semibold disabled:opacity-50">
          <Radio className="size-5 text-brand" /> {g.share ? t("Sharing") : t("Share location")}
        </button>
        <button onClick={() => setCalling(true)} className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 px-2 py-2.5 text-xs font-semibold">
          <Phone className="size-5" /> {t("Fake call")}
        </button>
      </div>
      {g.guardian_mode && active && <p className="mt-1.5 text-center text-[11px] text-muted">{t("Guardian mode is on: shake your phone hard three times for SOS.")}</p>}
      {!g.guardian_mode && <p className="mt-1.5 text-center text-[11px] text-muted">{t("Turn on Guardian mode in Account to share your location automatically if something goes wrong.")}</p>}
      {calling && <FakeCall name={g.fake_call_name} onEnd={() => setCalling(false)} />}
    </>
  );
}

// --- Fake incoming call --------------------------------------------------------------------------

export function FakeCall({ name, onEnd }: { name: string; onEnd: () => void }) {
  const [answered, setAnswered] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (answered) return;
    // A soft two-tone ring and vibration until it's answered or declined.
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    const ctx = Ctx ? new Ctx() : null;
    const ring = () => {
      navigator.vibrate?.([400, 200, 400]);
      if (!ctx) return;
      [440, 480].forEach((freq) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        gain.gain.value = 0.05;
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 1.2);
      });
    };
    ring();
    const id = setInterval(ring, 3000);
    return () => {
      clearInterval(id);
      navigator.vibrate?.(0);
      ctx?.close().catch(() => undefined);
    };
  }, [answered]);
  useEffect(() => {
    if (!answered) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [answered]);
  const seconds = answered ? Math.floor((now - answered) / 1000) : 0;
  return (
    <div className="fixed inset-0 z-[1200] flex flex-col items-center justify-between bg-gradient-to-b from-slate-800 to-slate-950 px-6 pb-16 pt-24 text-white">
      <div className="text-center">
        <div className="mx-auto mb-4 flex size-24 items-center justify-center rounded-full bg-white/10 text-4xl font-semibold">{name.slice(0, 1).toUpperCase()}</div>
        <div className="text-3xl font-semibold">{name}</div>
        <div className="mt-2 text-sm opacity-70">{answered ? `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}` : t("mobile · incoming call")}</div>
      </div>
      <div className="flex w-full max-w-xs justify-between">
        <button onClick={onEnd} className="flex size-16 items-center justify-center rounded-full bg-red-500" aria-label={t("Decline")}>
          <PhoneOff className="size-7" />
        </button>
        {!answered && (
          <button onClick={() => setAnswered(Date.now())} className="flex size-16 animate-bounce items-center justify-center rounded-full bg-green-500" aria-label={t("Answer")}>
            <Phone className="size-7" />
          </button>
        )}
      </div>
    </div>
  );
}

// --- Ops: open Guardian alerts -------------------------------------------------------------------

interface OpenShare {
  id: number;
  rider: string;
  phone: string;
  triggers: string[];
  started_at: string;
  contacts_alerted: number;
  reminders_sent: number;
  last_at: string | null;
  last_source: string;
  trip_number: string | null;
  link: string;
  lat: number | null;
  lng: number | null;
}

export function OpsGuardianShares() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "guardian"], queryFn: () => api.get<OpenShare[]>("safety/guardian/active/"), refetchInterval: 15_000 });
  const close = useMutation({
    mutationFn: (id: number) => api.post(`safety/guardian/${id}/close/`),
    onSuccess: () => {
      toast.success(t("Alert closed; the contacts have been told."));
      qc.invalidateQueries({ queryKey: ["ops", "guardian"] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const rows = q.data ?? [];
  return (
    <div className="mt-4 rounded-2xl border border-line p-4">
      <div className="mb-2 flex items-center gap-2 font-semibold">
        <Radio className={clsx("size-4", rows.length ? "animate-pulse text-danger" : "text-muted")} /> {t("Guardian alerts (location shared with family)")}
        <span className="ml-auto text-xs font-normal text-muted">{rows.length} {t("open")}</span>
      </div>
      {rows.length === 0 && <p className="text-sm text-muted">{t("No rider is sharing an emergency location right now.")}</p>}
      <div className="divide-y divide-line">
        {rows.map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <div className="min-w-0 flex-1">
              <div className="font-semibold">
                {s.rider} <span className="font-normal text-muted">· {s.phone}</span>
              </div>
              <div className="text-xs text-muted">
                {s.triggers.join(", ").toLowerCase()} · {s.contacts_alerted} {t("contacts told")} · {s.trip_number ?? t("no trip")} · {t("last location")} {s.last_at ? new Date(s.last_at).toLocaleTimeString() : "—"} ({s.last_source.toLowerCase() || "—"})
                {s.reminders_sent > 0 && ` · ${s.reminders_sent} ${t("quiet-phone reminders")}`}
              </div>
            </div>
            <a href={s.link} target="_blank" rel="noreferrer" className="text-xs font-semibold text-brand">
              {t("What family sees")}
            </a>
            <Button size="sm" variant="outline" onClick={() => window.confirm(t("Close this alert? Only after you've confirmed the rider is safe.")) && close.mutate(s.id)}>
              {t("Close")}
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
