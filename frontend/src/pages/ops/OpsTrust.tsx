/**
 * Trust & privacy desk: data requests (DPDP), appeals (two-person rule), the insurance claims
 * desk, support quality (CSAT, help centre) and offers to opted-in riders.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { FileWarning, Gavel, Megaphone, ShieldCheck, Smile } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Input, PageHeader, Segmented, Stat, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { ago, dateTime, inr } from "@/lib/format";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

interface Overview {
  privacy: { open: number; overdue: number; by_kind: Record<string, number>; response_days: number };
  requests: { id: number; number: string; kind: string; kind_label: string; status: string; status_label: string; details: string; due_at: string; execute_after: string | null; outcome: string; created_at: string; user_label: string }[];
  appeals: { id: number; number: string; subject_label: string; status: string; status_label: string; user_name: string; original_reason: string; original_decided_by: number | null; original_decided_by_name: string | null; statement: string; due_at: string; decision_note: string; reviewed_by_name: string | null; created_at: string }[];
  open_appeals: number;
  claims: { id: number; number: string; trip_number: string; kind_label: string; status: string; status_label: string; claimant_name: string; description: string; amount_claimed: string; amount_approved: string | null; insurer_reference: string; decision_note: string; created_at: string; documents: { id: number; label: string; url: string }[] }[];
  open_claims: number;
  marketing_audience: number;
}

export default function OpsTrust() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "privacy";
  const q = useQuery({ queryKey: ["ops", "trust"], queryFn: () => api.get<Overview>("ops/trust/overview/"), refetchInterval: 30_000 });
  const quality = useQuery({ queryKey: ["ops", "trust", "csat"], queryFn: () => api.get<{ csat: { ratings: number; average: number | null; csat_percent: number | null; by_category: { category: string; average: number; ratings: number }[]; recent_comments: { score: number; comment: string; ticket__ticket_number: string }[] }; help: { articles: number; views: number; helpful_percent: number | null; deflections: number; needs_work: { slug: string; title: string; up: number; down: number }[] } }>("ops/trust/csat/"), enabled: tab === "quality" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "trust"] });
  const onError = (err: unknown) => toast.error(errorText(err));
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const resolve = useMutation({ mutationFn: ({ id, reject }: { id: number; reject: boolean }) => api.post(`ops/trust/requests/${id}/resolve/`, { outcome: notes[`r${id}`] ?? "", reject }), onSuccess: refresh, onError });
  const decideAppeal = useMutation({ mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post(`ops/trust/appeals/${id}/decide/`, { approve, note: notes[`a${id}`] ?? "" }), onSuccess: () => { toast.success("Decision sent"); refresh(); }, onError });
  const review = useMutation({ mutationFn: (id: number) => api.post(`ops/trust/claims/${id}/review/`), onSuccess: refresh, onError });
  const decideClaim = useMutation({ mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post(`ops/trust/claims/${id}/decide/`, { approve, note: notes[`c${id}`] ?? "", amount: amounts[id] ? Number(amounts[id]) : null }), onSuccess: () => { toast.success("Claim decided"); refresh(); }, onError });
  const [offer, setOffer] = useState({ title: "", body: "" });
  const sendOffer = useMutation({ mutationFn: () => api.post<{ sent: number }>("ops/trust/offer/", offer), onSuccess: (r) => { toast.success(`Sent to ${r.sent} riders who opted in`); setOffer({ title: "", body: "" }); }, onError });
  const o = q.data;
  const note = (key: string, placeholder: string) => <Textarea rows={2} className="mt-2" value={notes[key] ?? ""} onChange={(e) => setNotes({ ...notes, [key]: e.target.value })} placeholder={placeholder} />;
  return (
    <>
      <PageHeader title="Trust & privacy" subtitle="Personal data requests (India's DPDP Act), appeals reviewed by a second person, the insurance claims desk, and support quality." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Privacy requests open" value={o?.privacy.open ?? "—"} sub={o ? `${o.privacy.overdue} overdue · answer within ${o.privacy.response_days} days` : ""} icon={<ShieldCheck className="size-4" />} tone={o?.privacy.overdue ? "danger" : "brand"} />
        <Stat label="Appeals waiting" value={o?.open_appeals ?? "—"} icon={<Gavel className="size-4" />} tone="warning" />
        <Stat label="Claims open" value={o?.open_claims ?? "—"} icon={<FileWarning className="size-4" />} tone="info" />
        <Stat label="Riders opted in to offers" value={o?.marketing_audience ?? "—"} icon={<Megaphone className="size-4" />} />
      </div>
      <div className="mt-4">
        <Segmented value={tab} onChange={(v) => setParams({ tab: v })} options={[{ value: "privacy", label: "Privacy" }, { value: "appeals", label: "Appeals" }, { value: "claims", label: "Claims" }, { value: "quality", label: "Support quality" }, { value: "offers", label: "Offers" }]} />
      </div>
      <div className="mt-4 space-y-3">
        {tab === "privacy" &&
          (o?.requests ?? []).map((r) => {
            const open = ["RECEIVED", "IN_PROGRESS"].includes(r.status);
            return (
              <Card key={r.id} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{r.kind_label}</span>
                  <span className="text-xs text-muted">
                    {r.number} · {r.user_label} · {ago(r.created_at)}
                  </span>
                  <span className="flex-1" />
                  <Badge tone={r.status === "COMPLETED" ? "brand" : r.status === "WAITING" ? "warning" : open && new Date(r.due_at) < new Date() ? "danger" : "neutral"}>{r.status_label}</Badge>
                </div>
                {r.details && <p className="mt-1 text-sm">{r.details}</p>}
                <p className="text-xs text-muted">
                  {r.status === "WAITING" && r.execute_after ? `Deleted automatically on ${dateTime(r.execute_after)} unless cancelled` : `Answer by ${dateTime(r.due_at)}`}
                  {r.outcome && ` · ${r.outcome}`}
                </p>
                {open && r.kind !== "EXPORT" && (
                  <>
                    {note(`r${r.id}`, "What was done (sent to the person)")}
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" onClick={() => resolve.mutate({ id: r.id, reject: false })}>
                        Done
                      </Button>
                      <Button size="sm" variant="ghost" className="text-danger" onClick={() => resolve.mutate({ id: r.id, reject: true })}>
                        Reject with reason
                      </Button>
                    </div>
                  </>
                )}
              </Card>
            );
          })}
        {tab === "appeals" &&
          (o?.appeals ?? []).map((a) => (
            <Card key={a.id} className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{a.subject_label}</span>
                <span className="text-xs text-muted">
                  {a.number} · {a.user_name} · due {dateTime(a.due_at)}
                </span>
                <span className="flex-1" />
                <Badge tone={a.status === "UPHELD" ? "brand" : a.status === "DENIED" ? "danger" : "warning"}>{a.status_label}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted">
                Original decision: {a.original_reason}
                {a.original_decided_by_name && ` (by ${a.original_decided_by_name}, who can't review this appeal)`}
              </p>
              <p className="mt-2 rounded-xl bg-surface-2 p-3 text-sm">“{a.statement}”</p>
              {a.status === "OPEN" ? (
                <>
                  {note(`a${a.id}`, "Your decision, explained to them")}
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" onClick={() => decideAppeal.mutate({ id: a.id, approve: true })}>
                      Accept and reverse
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => decideAppeal.mutate({ id: a.id, approve: false })}>
                      Keep the decision
                    </Button>
                  </div>
                </>
              ) : (
                <p className="mt-2 text-xs">
                  {a.reviewed_by_name}: {a.decision_note}
                </p>
              )}
            </Card>
          ))}
        {tab === "claims" &&
          (o?.claims ?? []).map((c) => {
            const open = ["SUBMITTED", "UNDER_REVIEW"].includes(c.status);
            return (
              <Card key={c.id} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">
                    {c.kind_label} · {inr(c.amount_claimed, { whole: true })}
                  </span>
                  <span className="text-xs text-muted">
                    {c.number} · {c.claimant_name} · {c.trip_number}
                    {c.insurer_reference && ` · insurer ${c.insurer_reference}`}
                  </span>
                  <span className="flex-1" />
                  <Badge tone={c.status === "PAID" ? "brand" : c.status === "REJECTED" ? "danger" : "info"}>{c.status_label}</Badge>
                </div>
                <p className="mt-1 text-sm">{c.description}</p>
                {c.documents.length > 0 && (
                  <div className="mt-1 flex gap-2 text-xs">
                    {c.documents.map((d) => (
                      <a key={d.id} href={d.url} target="_blank" rel="noreferrer" className="text-brand-strong underline">
                        {d.label || "Document"}
                      </a>
                    ))}
                  </div>
                )}
                {c.status === "SUBMITTED" && (
                  <Button size="sm" variant="outline" className="mt-2" onClick={() => review.mutate(c.id)}>
                    Send to insurer
                  </Button>
                )}
                {open && (
                  <>
                    {note(`c${c.id}`, "Decision note")}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input className="!w-32 !py-1.5" inputMode="numeric" placeholder={`≤ ${Number(c.amount_claimed).toFixed(0)}`} value={amounts[c.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [c.id]: e.target.value.replace(/\D/g, "") })} />
                      <Button size="sm" onClick={() => decideClaim.mutate({ id: c.id, approve: true })}>
                        Approve and pay
                      </Button>
                      <Button size="sm" variant="ghost" className="text-danger" onClick={() => decideClaim.mutate({ id: c.id, approve: false })}>
                        Reject
                      </Button>
                    </div>
                  </>
                )}
                {!open && c.decision_note && <p className={clsx("mt-2 text-xs")}>{c.decision_note}</p>}
              </Card>
            );
          })}
        {tab === "quality" && quality.data && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <CardHeader title="Support satisfaction (30 days)" subtitle="Share of 4 and 5 star ratings after a ticket is resolved." />
              <div className="flex items-baseline gap-3">
                <Smile className="size-6 text-brand-strong" />
                <span className="text-3xl font-bold">{quality.data.csat.csat_percent ?? "—"}%</span>
                <span className="text-sm text-muted">
                  avg {quality.data.csat.average ?? "—"} · {quality.data.csat.ratings} ratings
                </span>
              </div>
              {quality.data.csat.by_category.map((c) => (
                <div key={c.category} className="flex justify-between py-1 text-sm">
                  <span>{c.category.replaceAll("_", " ").toLowerCase()}</span>
                  <span className="font-semibold">
                    {c.average} <span className="font-normal text-muted">({c.ratings})</span>
                  </span>
                </div>
              ))}
              <div className="mt-3 space-y-1">
                {quality.data.csat.recent_comments.map((c, i) => (
                  <p key={i} className="text-xs">
                    <span className="text-amber-500">{"★".repeat(c.score)}</span> {c.comment} <span className="text-muted">· {c.ticket__ticket_number}</span>
                  </p>
                ))}
              </div>
            </Card>
            <Card className="p-4">
              <CardHeader title="Help centre" subtitle="Questions answered without a ticket: a helpful vote and no ticket in the next hour." />
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-xl font-bold">{quality.data.help.views.toLocaleString("en-IN")}</div>
                  <div className="text-xs text-muted">article views</div>
                </div>
                <div>
                  <div className="text-xl font-bold">{quality.data.help.helpful_percent ?? "—"}%</div>
                  <div className="text-xs text-muted">helpful</div>
                </div>
                <div>
                  <div className="text-xl font-bold">{quality.data.help.deflections}</div>
                  <div className="text-xs text-muted">solved without a ticket</div>
                </div>
              </div>
              {quality.data.help.needs_work.length > 0 && <div className="mt-3 text-xs font-semibold text-muted uppercase">Needs rewriting</div>}
              {quality.data.help.needs_work.map((a) => (
                <div key={a.slug} className="text-sm">
                  {a.title} <span className="text-xs text-muted">(👍 {a.up} · 👎 {a.down})</span>
                </div>
              ))}
            </Card>
          </div>
        )}
        {tab === "offers" && (
          <Card className="max-w-xl p-4">
            <CardHeader title="Announce an offer" subtitle={`Only riders who switched on "Offers and promotions" receive it (${o?.marketing_audience ?? 0} right now). Nobody else is messaged.`} />
            <Input value={offer.title} onChange={(e) => setOffer({ ...offer, title: e.target.value })} placeholder="20% off Mini rides this weekend" />
            <Textarea className="mt-2" rows={3} value={offer.body} onChange={(e) => setOffer({ ...offer, body: e.target.value })} placeholder="Use code WEEKEND20, up to ₹60 off, until Sunday midnight." />
            <Button className="mt-2" icon={<Megaphone className="size-4" />} disabled={offer.title.length < 5} loading={sendOffer.isPending} onClick={() => sendOffer.mutate()}>
              Send to opted-in riders
            </Button>
          </Card>
        )}
        {o && tab === "privacy" && o.requests.length === 0 && <EmptyState icon={<ShieldCheck className="size-6" />} title="No privacy requests" />}
      </div>
    </>
  );
}
