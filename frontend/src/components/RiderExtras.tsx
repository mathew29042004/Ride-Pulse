/**
 * Rider product features: accessibility needs, teen accounts (parent and teen sides), the
 * weather and events strip on Home, and links to the corporate dashboard.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Briefcase, ChevronRight, CloudRain, PartyPopper, Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Input, Modal } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";
import { ACCESSIBILITY } from "@/lib/preferences";
import type { Rider } from "@/lib/types";

import { useProfiles } from "./Profiles";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

// --- Accessibility ---------------------------------------------------------------------------

export function AccessibilitySettings({ rider }: { rider: Rider }) {
  const qc = useQueryClient();
  const needs = rider.accessibility ?? [];
  const save = useMutation({
    mutationFn: (accessibility: string[]) => api.patch<Rider>("rider/me/", { accessibility }),
    onSuccess: (me) => qc.setQueryData(["rider", "me"], me),
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <>
      <h2 className="mt-6 text-xs font-semibold tracking-wide text-muted uppercase">{t("Accessibility")}</h2>
      <p className="mb-2 text-xs text-muted">{t("Sent with every ride. Riders who need help boarding get 5 extra minutes of free waiting.")}</p>
      <div className="space-y-1.5">
        {ACCESSIBILITY.map(({ value, label, hint, icon: Icon }) => {
          const on = needs.includes(value);
          return (
            <button
              key={value}
              onClick={() => save.mutate(on ? needs.filter((v) => v !== value) : [...needs, value])}
              aria-pressed={on}
              className={clsx("flex w-full items-start gap-3 rounded-2xl border px-3 py-2.5 text-left", on ? "border-fg bg-surface-2" : "border-line")}
            >
              <Icon className="mt-0.5 size-4 shrink-0" />
              <span className="flex-1">
                <span className="block text-sm font-semibold">{t(label)}</span>
                <span className="block text-xs text-muted">{t(hint)}</span>
              </span>
              <span className={clsx("mt-0.5 size-4 shrink-0 rounded-full border-2", on ? "border-brand bg-brand" : "border-line")} />
            </button>
          );
        })}
      </div>
    </>
  );
}

// --- Teen accounts ---------------------------------------------------------------------------

interface TeenState {
  teens: {
    id: number;
    name: string;
    status: "INVITED" | "ACTIVE";
    curfew: [number, number];
    monthly_limit: string | null;
    spent_this_month: string;
    active_trip: { status: string; track: string | null } | null;
  }[];
  my_guardian: { id: number; name: string; status: "INVITED" | "ACTIVE"; curfew: [number, number] } | null;
}

export function TeenAccounts() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["rider", "teens"], queryFn: () => api.get<TeenState>("rider/teens/"), refetchInterval: 30_000 });
  const done = (data: TeenState) => qc.setQueryData(["rider", "teens"], data);
  const onError = (err: unknown) => toast.error(errorText(err));
  const [adding, setAdding] = useState(false);
  const [phone, setPhone] = useState("");
  const [limit, setLimit] = useState("2000");
  const [year, setYear] = useState("");
  const invite = useMutation({
    mutationFn: () => api.post<TeenState>("rider/teens/", { phone, monthly_limit: limit ? Number(limit) : null }),
    onSuccess: (data) => {
      done(data);
      setAdding(false);
      setPhone("");
      toast.success(t("Invitation sent to your teen"));
    },
    onError,
  });
  const accept = useMutation({ mutationFn: (id: number) => api.post<TeenState>(`rider/teens/${id}/accept/`, { birth_year: Number(year) }), onSuccess: done, onError });
  const end = useMutation({ mutationFn: (id: number) => api.post<TeenState>(`rider/teens/${id}/end/`), onSuccess: done, onError });
  const s = q.data;
  if (!s) return null;
  const hours = (c: [number, number]) => `${c[0]}:00 – ${c[1]}:00`;
  return (
    <>
      <div className="mt-6 flex items-center justify-between">
        <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">{t("Teen accounts")}</h2>
        {!s.my_guardian && (
          <button onClick={() => setAdding(true)} className="flex items-center gap-1 text-xs font-semibold text-brand-strong">
            <Plus className="size-3.5" /> {t("Add a teen")}
          </button>
        )}
      </div>
      {s.my_guardian ? (
        <div className="mt-2 rounded-2xl border border-line p-3 text-sm">
          <div className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="size-4 text-brand-strong" /> {t("Teen account with {name}", { name: s.my_guardian.name })}
          </div>
          {s.my_guardian.status === "INVITED" ? (
            <div className="mt-2 flex gap-2">
              <Input inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder={t("Your birth year")} className="!py-2" />
              <Button size="sm" disabled={year.length !== 4} onClick={() => accept.mutate(s.my_guardian!.id)}>
                {t("Accept")}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => end.mutate(s.my_guardian!.id)}>
                {t("Decline")}
              </Button>
            </div>
          ) : (
            <p className="mt-1 text-xs text-muted">{t("Paid by your parent and shared with them live. No rides {hours}. Cars and autos only.", { hours: hours(s.my_guardian.curfew) })}</p>
          )}
        </div>
      ) : s.teens.length === 0 ? (
        <p className="mt-2 text-sm text-muted">{t("Let your 13-17 year old ride: you pay, follow every ride live, and set a curfew and a monthly limit.")}</p>
      ) : (
        <div className="mt-2 space-y-2">
          {s.teens.map((teen) => (
            <div key={teen.id} className="rounded-2xl border border-line p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{teen.name}</span>
                <span className="text-xs text-muted">{teen.status === "INVITED" ? t("Waiting for them to accept") : t("No rides {hours}", { hours: hours(teen.curfew) })}</span>
              </div>
              <div className="mt-1 text-xs text-muted">
                {t("{spent} this month", { spent: inr(teen.spent_this_month) })}
                {teen.monthly_limit && ` · ${t("limit {limit}", { limit: inr(teen.monthly_limit, { whole: true }) })}`}
              </div>
              {teen.active_trip && (
                <div className="mt-2 flex items-center justify-between rounded-xl bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:bg-sky-500/10 dark:text-sky-200">
                  <span>{t("On a ride now: {status}", { status: teen.active_trip.status })}</span>
                  {teen.active_trip.track && (
                    <a href={teen.active_trip.track} target="_blank" rel="noreferrer" className="font-semibold underline">
                      {t("Follow live")}
                    </a>
                  )}
                </div>
              )}
              <button onClick={() => end.mutate(teen.id)} className="mt-2 text-xs font-semibold text-danger">
                {t("End teen account")}
              </button>
            </div>
          ))}
        </div>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title={t("Add a teen")} footer={<Button block loading={invite.isPending} disabled={phone.replace(/\D/g, "").length < 10} onClick={() => invite.mutate()}>{t("Send invitation")}</Button>}>
        <p className="text-sm text-muted">{t("Your teen signs up with their own number first, then accepts here. Their rides are paid by you, shared with you live, top-rated drivers only, cars and autos only, no rides 10 pm – 6 am.")}</p>
        <Input className="mt-3" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("Your teen's mobile number")} />
        <Input className="mt-2" inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))} placeholder={t("Monthly limit (₹)")} />
      </Modal>
    </>
  );
}

// --- Corporate dashboard links ---------------------------------------------------------------

export function BusinessLinks() {
  const profiles = (useProfiles().data ?? []).filter((p) => p.kind === "BUSINESS" && (p.role === "OWNER" || p.is_admin));
  if (!profiles.length) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {profiles.map((p) => (
        <Link key={p.id} to={`/ride/business/${p.id}`} className="flex items-center gap-3 rounded-2xl bg-surface-2 px-3 py-3 text-sm">
          <Briefcase className="size-4" />
          <span className="flex-1 font-semibold">{t("{name}: company dashboard", { name: p.name })}</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
      ))}
    </div>
  );
}

// --- Weather and events on Home --------------------------------------------------------------

export function ContextStrip({ lat, lng }: { lat: number; lng: number }) {
  const q = useQuery({
    queryKey: ["context", lat.toFixed(2), lng.toFixed(2)],
    queryFn: () => api.get<{ weather: { condition: string; temperature_c: string } | null; messages: string[]; events: unknown[] }>(`intel/nearby/?lat=${lat}&lng=${lng}`),
    staleTime: 10 * 60_000,
  });
  const data = q.data;
  if (!data?.messages.length) return null;
  return (
    <div className="space-y-1.5">
      {data.messages.slice(0, 2).map((m) => (
        <div key={m} className="flex items-start gap-2 rounded-2xl bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:bg-sky-500/10 dark:text-sky-200">
          {m.includes("ends around") ? <PartyPopper className="mt-0.5 size-3.5 shrink-0" /> : <CloudRain className="mt-0.5 size-3.5 shrink-0" />}
          <span>{m}</span>
        </div>
      ))}
    </div>
  );
}
