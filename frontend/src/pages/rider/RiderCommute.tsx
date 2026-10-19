/** Office commute: join your company's plan with your home pick-up; rides are booked every
 * evening for the next day and paid by the company. Skip a day for leave or work from home. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Building2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { PlacePick, type Picked } from "@/components/PlacePick";
import { Button, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { t } from "@/lib/i18n";

interface Plan {
  id: number;
  name: string;
  company: string;
  office_name: string;
  ride_type_name: string;
  weekdays_label: string;
  arrive_by: string;
  leave_at: string;
}
interface Enrolment {
  id: number;
  company: string;
  plan: Plan;
  home_address: string;
  morning: boolean;
  evening: boolean;
  skip_dates: string[];
  upcoming: { id: number; at: string; to: string }[];
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function RiderCommute() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["commute"], queryFn: () => api.get<{ enrolments: Enrolment[]; plans: Plan[] }>("rider/commute/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["commute"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : t("Something went wrong."));
  const [joining, setJoining] = useState<Plan | null>(null);
  const [home, setHome] = useState<Picked | null>(null);
  const [morning, setMorning] = useState(true);
  const [evening, setEvening] = useState(true);
  const enrol = useMutation({
    mutationFn: () => api.post("rider/commute/enrol/", { plan: joining!.id, home_lat: home!.lat, home_lng: home!.lng, home_address: `${home!.name}, ${home!.address}`, morning, evening }),
    onSuccess: () => { toast.success(t("You're in. Rides are booked each evening for the next day.")); setJoining(null); refresh(); },
    onError: fail,
  });
  const skip = useMutation({
    mutationFn: (v: { enrolment: number; date: string; skip: boolean }) => api.post("rider/commute/skip/", v),
    onSuccess: refresh,
    onError: fail,
  });
  const leave = useMutation({ mutationFn: (id: number) => api.post("rider/commute/leave/", { enrolment: id }), onSuccess: refresh, onError: fail });
  const days = Array.from({ length: 7 }, (_, i) => new Date(Date.now() + (i + 1) * 86_400_000));
  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <div className="flex items-center gap-2">
        <Link to="/ride/account" className="flex size-10 items-center justify-center rounded-full bg-surface-2" aria-label={t("Back")}>
          <ArrowLeft className="size-5" />
        </Link>
        <h1 className="text-xl font-bold">{t("Office commute")}</h1>
      </div>
      <p className="mt-2 text-sm text-muted">{t("Your company books your rides to and from the office and pays for them. Skip any day by the night before.")}</p>

      {q.data?.enrolments.map((e) => (
        <div key={e.id} className="mt-4 rounded-3xl border border-line p-4 text-sm">
          <div className="flex items-center gap-2 font-semibold"><Building2 className="size-5" /> {e.company} · {e.plan.name}</div>
          <div className="mt-1 text-xs text-muted">
            {e.plan.weekdays_label} · {t("arrive by {a}, leave {b}", { a: e.plan.arrive_by, b: e.plan.leave_at })} · {e.plan.ride_type_name}
          </div>
          <div className="mt-1 text-xs">{t("From")}: {e.home_address || t("your home")} → {e.plan.office_name}</div>
          <div className="mt-3 font-semibold">{t("Next 7 days")}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {days.map((d) => {
              const day = iso(d);
              const skipped = e.skip_dates.includes(day);
              return (
                <button key={day} onClick={() => skip.mutate({ enrolment: e.id, date: day, skip: !skipped })} className={`rounded-xl px-2 py-1 text-xs ${skipped ? "bg-surface-2 text-muted line-through" : "bg-brand/15"}`}>
                  {d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-[11px] text-muted">{t("Tap a day to skip it (leave, work from home); tap again to undo.")}</p>
          {e.upcoming.length > 0 && (
            <div className="mt-3 space-y-1 text-xs">
              {e.upcoming.map((r) => <div key={r.id}>{dateTime(r.at)} → {r.to}</div>)}
            </div>
          )}
          <button className="mt-3 text-xs text-danger" onClick={() => leave.mutate(e.id)}>{t("Leave this plan")}</button>
        </div>
      ))}

      {q.data && q.data.plans.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Plans from your companies")}</h2>
          {q.data.plans.map((p) => (
            <div key={p.id} className="mb-2 rounded-3xl border border-line p-4 text-sm">
              <div className="font-semibold">{p.company} · {p.name}</div>
              <div className="text-xs text-muted">{p.office_name} · {p.weekdays_label} · {p.arrive_by}–{p.leave_at}</div>
              {joining?.id === p.id ? (
                <div className="mt-3 space-y-2">
                  <PlacePick value={home} onChange={setHome} placeholder={t("Search for your home pick-up")} />
                  <Toggle checked={morning} onChange={setMorning} label={t("Morning ride to the office")} />
                  <Toggle checked={evening} onChange={setEvening} label={t("Evening ride home")} />
                  <Button block disabled={!home || !(morning || evening)} loading={enrol.isPending} onClick={() => enrol.mutate()}>{t("Join")}</Button>
                </div>
              ) : (
                <Button className="mt-2" size="sm" onClick={() => setJoining(p)}>{t("Join")}</Button>
              )}
            </div>
          ))}
        </div>
      )}
      {q.data && !q.data.enrolments.length && !q.data.plans.length && (
        <p className="mt-6 text-center text-sm text-muted">{t("Your company hasn't set up a commute plan yet. Ask your travel admin.")}</p>
      )}
    </div>
  );
}
