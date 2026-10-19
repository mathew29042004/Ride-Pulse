/**
 * Safety+: the "Is everything OK?" Ride Check prompt, Night Safe mode on the trip screens,
 * "I'm home safe", trusted contacts in Account, and the ops Ride Check queue.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { HeartHandshake, House, KeyRound, Moon, ShieldAlert, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Card, CardHeader, EmptyState, Field, Input, Modal, Select, StatusBadge, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Paginated, RideCheck, Rider, TrustedContact, Trip } from "@/lib/types";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const HOME_SAFE_HOURS = 3;

/** Shown over the trip screen when the server asks "Is everything OK?". */
export function RideCheckPrompt({ trip, role }: { trip: Trip; role: "rider" | "driver" }) {
  const qc = useQueryClient();
  const check = trip.open_ride_check;
  const answer = useMutation({
    mutationFn: (ok: boolean) => api.post<RideCheck>(`ride-checks/${check!.id}/answer/`, { ok }),
    onSuccess: (_row, ok) => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      if (ok) toast.success(t("Thanks. We'll keep watching the trip."));
      else toast.error(t("Our safety team has been alerted and will call you now."), { duration: 8000 });
    },
    onError: (err) => toast.error(errorText(err, "Couldn't send your answer.")),
  });
  if (!check) return null;

  return (
    <div className="rp-overlay absolute inset-x-3 top-16 z-[800] rounded-3xl border-2 border-amber-400 bg-surface p-4 shadow-[var(--shadow-float)]" role="alertdialog" aria-labelledby="ride-check-title">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300">
          <ShieldAlert className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="ride-check-title" className="font-bold">
            {(role === "rider" ? t("Is everything OK?") : t("Are you OK?"))}
          </h2>
          <p className="text-sm text-muted">{t(check.kind_label)}.</p>
          {role === "rider" && <p className="mt-1 text-xs text-muted">{t("If we don't hear back in a few minutes, our safety team will check on you.")}</p>}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button variant="brand" loading={answer.isPending && answer.variables === true} onClick={() => answer.mutate(true)}>
          {t("I'm OK")}
        </Button>
        <Button variant="danger" loading={answer.isPending && answer.variables === false} onClick={() => answer.mutate(false)}>
          {t("Get help")}
        </Button>
      </div>
    </div>
  );
}

/** During a Night Safe ride: what it does, and (rider) "End my ride here". */
export function NightSafeBar({ trip, role }: { trip: Trip; role: "rider" | "driver" }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const early = useMutation({
    mutationFn: () => api.post<Trip>(`trips/${trip.id}/early-drop/`),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success(t("Your driver can end the trip here."));
    },
    onError: (err) => toast.error(errorText(err, "Couldn't confirm.")),
  });
  if (!trip.night_safe || trip.status !== "IN_PROGRESS") return null;

  return (
    <>
      <div className="mt-3 flex items-center gap-2 rounded-2xl bg-indigo-50 px-3 py-2.5 text-xs text-indigo-950 dark:bg-indigo-400/10 dark:text-indigo-100">
        <Moon className="size-4 shrink-0" />
        <span className="flex-1">
          {role === "driver" ? (
            <>
              <b>{t("Night Safe ride")}</b> · {t("End the trip at the drop point.")}
              {trip.early_drop_confirmed && ` ${t("The rider confirmed an earlier stop.")}`}
            </>
          ) : (
            <>
              <b>{t("Night Safe is on")}</b> · {(trip.contacts_notified_at ? t("Your contacts are following this ride.") : t("Extra safety checks are on."))}
            </>
          )}
        </span>
        {role === "rider" && !trip.early_drop_confirmed && (
          <button onClick={() => setConfirming(true)} className="shrink-0 rounded-full bg-white/70 px-2.5 py-1 font-semibold dark:bg-white/10">
            {t("End here")}
          </button>
        )}
      </div>
      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t("End your ride here?")}
        footer={
          <Button block loading={early.isPending} onClick={() => early.mutate()}>
            {t("Yes, drop me here")}
          </Button>
        }
      >
        <p className="text-sm text-muted">{t("On Night Safe rides your driver can only end the trip at your drop point. Confirm only if you want to get out here.")}</p>
      </Modal>
    </>
  );
}

/** After a Night Safe ride: one tap tells the contacts who followed it. */
export function HomeSafeButton({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const send = useMutation({
    mutationFn: () => api.post<Trip>(`trips/${trip.id}/home-safe/`),
    onSuccess: (updated) => {
      qc.setQueryData(["trips", String(trip.id)], updated);
      toast.success(t("We've told your contacts you're home safe."));
    },
    onError: (err) => toast.error(errorText(err, "Couldn't send the check-in.")),
  });
  const recent = trip.completed_at && Date.now() - new Date(trip.completed_at).getTime() < HOME_SAFE_HOURS * 3_600_000;
  if (trip.status !== "COMPLETED" || !trip.contacts_notified_at || !(recent || trip.home_safe_at)) return null;

  return trip.home_safe_at ? (
    <p className="mt-3 flex items-center gap-2 rounded-2xl bg-surface-2 px-4 py-3 text-sm text-muted">
      <ShieldCheck className="size-4 text-brand" /> {t("Your contacts know you're home safe.")}
    </p>
  ) : (
    <Button block variant="brand" className="mt-3" icon={<House className="size-4" />} loading={send.isPending} onClick={() => send.mutate()}>
      {t("I'm home safe")}
    </Button>
  );
}

const SHARE_MODES: { value: TrustedContact["share_mode"]; label: string }[] = [
  { value: "NIGHT", label: t("Night rides") },
  { value: "ALWAYS", label: t("Every ride") },
  { value: "NEVER", label: t("Only when I share") },
];

/** Account: Night Safe mode and up to three trusted contacts. */
export function SafetySettings({ rider }: { rider: Rider | undefined }) {
  const qc = useQueryClient();
  const contacts = useQuery({ queryKey: ["rider", "contacts"], queryFn: () => api.get<TrustedContact[]>("rider/contacts/") });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", share_mode: "NIGHT" as TrustedContact["share_mode"] });
  const refresh = () => qc.invalidateQueries({ queryKey: ["rider", "contacts"] });
  const nightMode = useMutation({
    mutationFn: (on: boolean) => api.patch<Rider>("rider/me/", { night_safety: on }),
    onSuccess: (me) => qc.setQueryData(["rider", "me"], me),
    onError: (err) => toast.error(errorText(err, "Couldn't change Night Safe mode.")),
  });
  const add = useMutation({
    mutationFn: () => api.post<TrustedContact>("rider/contacts/", form),
    onSuccess: () => {
      setAdding(false);
      setForm({ name: "", phone: "", share_mode: "NIGHT" });
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Couldn't add the contact.")),
  });
  const change = useMutation({
    mutationFn: ({ id, share_mode }: { id: number; share_mode: string }) => api.patch(`rider/contacts/${id}/`, { share_mode }),
    onSuccess: refresh,
    onError: (err) => toast.error(errorText(err, "Couldn't update.")),
  });
  const remove = useMutation({ mutationFn: (id: number) => api.del(`rider/contacts/${id}/`), onSuccess: refresh });
  const list = contacts.data ?? [];

  return (
    <>
      <div className="flex items-center gap-3 py-3.5">
        <Moon className="size-5" />
        <span className="flex-1">
          <span className="block font-medium">{t("Night Safe mode")}</span>
          <span className="block text-xs text-muted">{t("10 pm – 6 am and “woman driver” rides: stricter checks, contacts follow along, drop only at your destination.")}</span>
        </span>
        <Toggle checked={rider?.night_safety ?? true} onChange={(on) => nightMode.mutate(on)} label={t("Night Safe mode")} />
      </div>
      <RidePinSetting rider={rider} />
      <div className="py-3.5">
        <div className="flex items-center gap-3">
          <Users className="size-5" />
          <span className="flex-1">
            <span className="block font-medium">{t("Trusted contacts")}</span>
            <span className="block text-xs text-muted">{t("They get your live trip link by SMS. All of them are told if a Ride Check needs our safety team.")}</span>
          </span>
          {list.length < 3 && (
            <button onClick={() => setAdding(true)} className="rounded-full bg-surface-3 p-2" aria-label={t("Add a contact")}>
              <UserPlus className="size-4" />
            </button>
          )}
        </div>
        {list.length > 0 && (
          <div className="mt-2 space-y-1.5 pl-8">
            {list.map((c) => (
              <div key={c.id} className="flex items-center gap-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{c.name}</span>
                  <span className="block text-xs text-muted">{c.phone}</span>
                </span>
                <Select value={c.share_mode} onChange={(e) => change.mutate({ id: c.id, share_mode: e.target.value })} className="!w-auto !py-1 text-xs" aria-label={t("When to share")}>
                  {SHARE_MODES.map((m) => (
                    <option key={m.value} value={m.value}>
                      {t(m.label)}
                    </option>
                  ))}
                </Select>
                <button onClick={() => remove.mutate(c.id)} className="p-1 text-muted hover:text-danger" aria-label={`${t("Remove")} ${c.name}`}>
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title={t("Add a trusted contact")}
        footer={
          <Button onClick={() => add.mutate()} loading={add.isPending} disabled={!form.name.trim() || form.phone.replace(/\D/g, "").length < 10}>
            {t("Save")}
          </Button>
        }
      >
        <Field label={t("Name")}>
          <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Amma" />
        </Field>
        <Field label={t("Mobile number")} className="mt-3">
          <Input inputMode="tel" value={form.phone} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} placeholder="98765 43210" />
        </Field>
        <Field label={t("Share my trips")} className="mt-3">
          <Select value={form.share_mode} onChange={(e) => setForm((f) => ({ ...f, share_mode: e.target.value as TrustedContact["share_mode"] }))}>
            {SHARE_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {t(m.label)}
              </option>
            ))}
          </Select>
        </Field>
      </Modal>
    </>
  );
}

/** Ops safety desk: every Ride Check, unanswered ones first. */
export function OpsRideChecks() {
  const checks = useQuery({ queryKey: ["ride-checks"], queryFn: () => api.get<Paginated<RideCheck>>("ride-checks/?page_size=30"), refetchInterval: 10_000 });
  const rows = checks.data?.results ?? [];
  return (
    <Card className="mt-4">
      <CardHeader title={t("Ride Checks")} subtitle="Automatic “Is everything OK?” questions: long stops, off-route, running late, lost signal. Unanswered ones become SOS incidents." />
      {rows.length === 0 ? (
        <EmptyState icon={<HeartHandshake />} title={t("No Ride Checks yet")}>
          {t("They appear when a trip in progress looks unusual.")}
        </EmptyState>
      ) : (
        <div className="divide-y divide-line">
          {rows.map((c) => (
            <div key={c.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <ShieldAlert className={clsx("size-5 shrink-0", c.status === "ESCALATED" || c.status === "HELP" ? "text-danger" : c.status === "OPEN" ? "text-amber-500" : "text-muted")} />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">
                  {c.kind_label} · <Link to={`/ops/trips/${c.trip_id}`} className="hover:underline">{c.trip_number}</Link>
                </div>
                <div className="truncate text-xs text-muted">
                  {c.rider_name} with {c.driver_name || "driver"} · {ago(c.created_at)}
                  {c.driver_ok === true && " · driver says OK"}
                  {c.driver_ok === false && " · driver asked for help"}
                </div>
              </div>
              {c.incident_id && (
                <Link to={`/ops/safety/${c.incident_id}`} className="text-xs font-semibold text-danger hover:underline">
                  Incident →
                </Link>
              )}
              <StatusBadge status={c.status} label={c.status_label} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Set your own Ride PIN: the same 4 digits every trip (blank = a new random PIN each time). */
function RidePinSetting({ rider }: { rider: Rider | undefined }) {
  const qc = useQueryClient();
  const [pin, setPin] = useState<string | null>(null);
  const value = pin ?? rider?.ride_pin ?? "";
  const save = useMutation({
    mutationFn: (ride_pin: string) => api.patch<Rider>("rider/me/", { ride_pin }),
    onSuccess: (me) => {
      qc.setQueryData(["rider", "me"], me);
      setPin(null);
      toast.success(me.ride_pin ? t("Your Ride PIN is saved.") : t("You'll get a new PIN every trip."));
    },
    onError: (err) => toast.error(errorText(err, "Couldn't save the PIN.")),
  });
  return (
    <div className="flex items-center gap-3 py-3.5">
      <KeyRound className="size-5" />
      <span className="flex-1">
        <span className="block font-medium">{t("My Ride PIN")}</span>
        <span className="block text-xs text-muted">{t("Use the same 4 digits on every trip. Leave empty for a new PIN each time.")}</span>
      </span>
      <input
        value={value}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
        onBlur={() => pin !== null && pin !== (rider?.ride_pin ?? "") && (pin.length === 4 || pin === "") && save.mutate(pin)}
        inputMode="numeric"
        placeholder="––––"
        aria-label={t("My Ride PIN")}
        className="w-20 rounded-xl border border-line bg-surface px-2 py-1.5 text-center font-mono tracking-[0.3em]"
      />
    </div>
  );
}
