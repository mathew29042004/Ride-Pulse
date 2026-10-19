/** Ops → Powers: each specialist role's own tools, shown only to the roles that hold them.
 * Finance approves large refunds; safety bans for good; dispatch hands a waiting trip to a chosen
 * driver; compliance places legal holds; HR moves people (manager, city, role). The commander
 * and administrators see every section. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Gavel, Radio, ReceiptIndianRupee, Search, UserCog } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";

interface Data {
  refunds?: { id: number; trip: string; amount: string; reason: string; by: string; at: string; status: string; status_label: string; note: string }[];
  bans?: { id: number; user_id: number; who: string; kind: string; value: string; reason: string; at: string; lifted: boolean }[];
  holds?: { id: number; who: string; case: string; reason: string; at: string; released: boolean }[];
  waiting?: { id: number; trip: string; city: string; ride_type: string; pickup: string; waiting_min: number }[];
  roles?: { value: string; label: string }[];
}
interface Person {
  id: number;
  name: string;
  email: string;
  role: string;
  role_label: string;
  staff_profile: number | null;
  on_hold: boolean;
}

const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");

function PersonPicker({ value, onChange, staffOnly }: { value: Person | null; onChange: (p: Person | null) => void; staffOnly?: boolean }) {
  const [q, setQ] = useState("");
  const r = useQuery({
    queryKey: ["ops", "powers", "people", q],
    queryFn: () => api.get<{ results: Person[] }>(`ops/powers/people/?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 3 && !value,
  });
  if (value)
    return (
      <div className="flex items-center justify-between rounded-xl border border-line px-3 py-2 text-sm">
        <span><span className="font-semibold">{value.name}</span> <span className="text-muted">· {value.role_label}</span></span>
        <button className="text-xs font-semibold text-brand" onClick={() => onChange(null)}>Change</button>
      </div>
    );
  const rows = (r.data?.results ?? []).filter((p) => !staffOnly || p.staff_profile);
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
        <Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email or phone" aria-label="Find a person" />
      </div>
      {rows.length > 0 && (
        <div className="mt-1 divide-y divide-line rounded-xl border border-line">
          {rows.map((p) => (
            <button key={p.id} className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-2" onClick={() => onChange(p)}>
              <span className="font-medium">{p.name}</span> <span className="text-xs text-muted">{p.role_label} · {p.email}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Section({ icon, title, subtitle, children }: { icon: ReactNode; title: string; subtitle: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2">{icon} {title}</span>} subtitle={subtitle} />
      <div className="p-4">{children}</div>
    </Card>
  );
}

export default function OpsPowers() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "powers"], queryFn: () => api.get<Data>("ops/powers/"), refetchInterval: 20_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "powers"] });
  const d = q.data;
  return (
    <>
      <PageHeader title="Powers" subtitle="The actions your role is trusted with. Every one is recorded in the audit trail." />
      {q.error && <EmptyState title="Your role has no special powers here" />}
      <div className="grid gap-4 xl:grid-cols-2">
        {d?.refunds && <Refunds rows={d.refunds} onDone={refresh} />}
        {d?.waiting && <Dispatch rows={d.waiting} onDone={refresh} />}
        {d?.bans && <Bans rows={d.bans} onDone={refresh} />}
        {d?.holds && <Holds rows={d.holds} onDone={refresh} />}
        {d?.roles && <Transfers roles={d.roles} />}
      </div>
    </>
  );
}

function Refunds({ rows, onDone }: { rows: NonNullable<Data["refunds"]>; onDone: () => void }) {
  const [notes, setNotes] = useState<Record<number, string>>({});
  const decide = useMutation({
    mutationFn: (v: { id: number; approve: boolean }) => api.post(`ops/powers/refunds/${v.id}/decide/`, { approve: v.approve, note: notes[v.id] ?? "" }),
    onSuccess: (_, v) => {
      toast.success(v.approve ? "Approved. The money is in the rider's wallet." : "Declined. The rider has been told why.");
      onDone();
    },
    onError: fail,
  });
  return (
    <Section icon={<ReceiptIndianRupee className="size-4 text-brand" />} title="Large refunds" subtitle="Refunds above ₹2,000 wait for finance before money moves.">
      {!rows.length && <EmptyState title="Nothing waiting" />}
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.id} className="rounded-xl border border-line p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-base font-semibold tabular-nums">{inr(r.amount)}</span>
              <Badge tone={r.status === "PENDING" ? "warning" : r.status === "APPROVED" ? "brand" : "neutral"}>{r.status_label}</Badge>
            </div>
            <div className="text-muted">{r.reason}</div>
            <div className="text-xs text-muted">{r.by} · {dateTime(r.at)}{r.note ? ` · “${r.note}”` : ""}</div>
            {r.status === "PENDING" && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Input className="!w-auto flex-1 !py-1.5" placeholder="Note (needed to decline)" value={notes[r.id] ?? ""} onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} aria-label="Note" />
                <Button size="sm" variant="brand" loading={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: true })}>Approve</Button>
                <Button size="sm" variant="secondary" loading={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: false })}>Decline</Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Dispatch({ rows, onDone }: { rows: NonNullable<Data["waiting"]>; onDone: () => void }) {
  const [trip, setTrip] = useState<number | null>(null);
  const drivers = useQuery({
    queryKey: ["ops", "powers", "drivers", trip],
    queryFn: () => api.get<{ drivers: { id: number; name: string; km: number; rating: string }[] }>(`ops/powers/trips/${trip}/drivers/`),
    enabled: trip !== null,
  });
  const assign = useMutation({
    mutationFn: (driver: number) => api.post("ops/powers/assign/", { trip, driver }),
    onSuccess: () => {
      toast.success("Offered to that driver now.");
      setTrip(null);
      onDone();
    },
    onError: fail,
  });
  return (
    <Section icon={<Radio className="size-4 text-sky-500" />} title="Manual dispatch" subtitle="Hand a waiting trip to the driver you choose.">
      {!rows.length && <EmptyState title="No trips waiting">Every rider has a driver.</EmptyState>}
      <div className="space-y-2">
        {rows.map((t) => (
          <div key={t.id} className={`rounded-xl border p-3 text-sm ${trip === t.id ? "border-brand" : "border-line"}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">{t.trip} <span className="font-normal text-muted">· {t.city} · {t.ride_type}</span></span>
              <Badge tone={t.waiting_min >= 5 ? "danger" : "warning"}>{t.waiting_min} min</Badge>
            </div>
            <div className="truncate text-xs text-muted">{t.pickup}</div>
            {trip === t.id ? (
              <div className="mt-2 space-y-1">
                {drivers.data && !drivers.data.drivers.length && <p className="text-xs text-muted">No free drivers within 15 km.</p>}
                {drivers.data?.drivers.map((dr) => (
                  <div key={dr.id} className="flex items-center justify-between rounded-lg bg-surface-2 px-2 py-1.5">
                    <span>{dr.name} <span className="text-xs text-muted">· {dr.km} km · ★ {dr.rating}</span></span>
                    <Button size="sm" loading={assign.isPending} onClick={() => assign.mutate(dr.id)}>Offer</Button>
                  </div>
                ))}
              </div>
            ) : (
              <Button size="sm" variant="outline" className="mt-2" onClick={() => setTrip(t.id)}>Choose a driver</Button>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Bans({ rows, onDone }: { rows: NonNullable<Data["bans"]>; onDone: () => void }) {
  const [who, setWho] = useState<Person | null>(null);
  const [reason, setReason] = useState("");
  const ban = useMutation({
    mutationFn: () => api.post("ops/powers/ban/", { user: who?.id, reason }),
    onSuccess: () => {
      const id = who?.id;
      toast.success("Banned. They can't sign up again with that phone or licence.", {
        duration: 10 * 60_000,
        action: { label: "Undo", onClick: () => api.post("ops/powers/undo-ban/", { user: id }).then(() => { toast.success("Ban undone."); onDone(); }, fail) },
      });
      setWho(null);
      setReason("");
      onDone();
    },
    onError: fail,
  });
  const lift = useMutation({
    mutationFn: (user: number) => api.post("ops/powers/lift-ban/", { user, reason: "Lifted after review" }),
    onSuccess: onDone,
    onError: fail,
  });
  return (
    <Section icon={<Ban className="size-4 text-danger" />} title="Permanent bans" subtitle="Suspends or blocks them, and bans their phone and driving licence.">
      <div className="space-y-2">
        <PersonPicker value={who} onChange={setWho} />
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What happened (10+ characters)" aria-label="Reason" />
        <Button block variant="danger" disabled={!who || reason.trim().length < 10} loading={ban.isPending} onClick={() => ban.mutate()}>Ban for good</Button>
      </div>
      <div className="mt-4 divide-y divide-line">
        {rows.map((b) => (
          <div key={b.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <div>
              <div className="font-medium">{b.who} <span className="text-xs text-muted">· {b.kind.toLowerCase()} {b.value}</span></div>
              <div className="text-xs text-muted">{b.reason} · {dateTime(b.at)}</div>
            </div>
            {b.lifted ? <Badge tone="neutral">Lifted</Badge> : <Button size="sm" variant="ghost" loading={lift.isPending} onClick={() => lift.mutate(b.user_id)}>Lift</Button>}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Holds({ rows, onDone }: { rows: NonNullable<Data["holds"]>; onDone: () => void }) {
  const [who, setWho] = useState<Person | null>(null);
  const [caseRef, setCaseRef] = useState("");
  const [reason, setReason] = useState("");
  const hold = useMutation({
    mutationFn: () => api.post("ops/powers/hold/", { user: who?.id, case_reference: caseRef, reason }),
    onSuccess: () => {
      toast.success("Legal hold placed. Their data can't be erased until it's released.");
      setWho(null);
      setCaseRef("");
      setReason("");
      onDone();
    },
    onError: fail,
  });
  const release = useMutation({ mutationFn: (id: number) => api.post(`ops/powers/holds/${id}/release/`), onSuccess: onDone, onError: fail });
  return (
    <Section icon={<Gavel className="size-4 text-amber-500" />} title="Legal holds" subtitle="Freeze a person's data during a police or court case.">
      <div className="space-y-2">
        <PersonPicker value={who} onChange={setWho} />
        <div className="grid grid-cols-[140px_1fr] gap-2">
          <Input value={caseRef} onChange={(e) => setCaseRef(e.target.value)} placeholder="Case ref" aria-label="Case reference" />
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" aria-label="Reason" />
        </div>
        <Button block variant="outline" disabled={!who || !caseRef.trim() || reason.trim().length < 10} loading={hold.isPending} onClick={() => hold.mutate()}>Place hold</Button>
      </div>
      <div className="mt-4 divide-y divide-line">
        {rows.map((h) => (
          <div key={h.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <div>
              <div className="font-medium">{h.who} <span className="text-xs text-muted">· {h.case}</span></div>
              <div className="text-xs text-muted">{h.reason} · {dateTime(h.at)}</div>
            </div>
            {h.released ? <Badge tone="neutral">Released</Badge> : <Button size="sm" variant="ghost" loading={release.isPending} onClick={() => release.mutate(h.id)}>Release</Button>}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Transfers({ roles }: { roles: { value: string; label: string }[] }) {
  const [who, setWho] = useState<Person | null>(null);
  const [manager, setManager] = useState<Person | null>(null);
  const [role, setRole] = useState("");
  const [reason, setReason] = useState("");
  const move = useMutation({
    mutationFn: () => api.post("ops/powers/transfer/", { employee: who?.id, manager: manager?.staff_profile ?? null, role, reason }),
    onSuccess: () => {
      toast.success("Done. They've been told, and their team channels are updated.");
      setWho(null);
      setManager(null);
      setRole("");
      setReason("");
    },
    onError: fail,
  });
  return (
    <Section icon={<UserCog className="size-4 text-violet-500" />} title="Moves and promotions" subtitle="Change someone's manager or role. The top roles are the commander's to give.">
      <div className="space-y-2">
        <Field label="Employee"><PersonPicker value={who} onChange={setWho} staffOnly /></Field>
        <Field label="New manager (optional)"><PersonPicker value={manager} onChange={setManager} staffOnly /></Field>
        <Field label="New role (optional)">
          <Select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">Keep their role</option>
            {roles.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </Select>
        </Field>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (e.g. promoted after appraisal)" aria-label="Reason" />
        <Button block disabled={!who || (!manager && !role) || reason.trim().length < 5} loading={move.isPending} onClick={() => move.mutate()}>Make the change</Button>
      </div>
    </Section>
  );
}
