/**
 * Rider and driver: the privacy centre (consent, download, delete), the help centre, insurance
 * claims and appeals.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, Download, FileWarning, Gavel, Scale, Search, ShieldCheck, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { Button, Input, Modal, Select, Textarea, Toggle } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { t } from "@/lib/i18n";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

function Back({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="mb-3 inline-flex items-center gap-1 text-sm text-muted">
      <ArrowLeft className="size-4" /> {label}
    </Link>
  );
}

// --- Privacy centre --------------------------------------------------------------------------

interface DataRequest {
  id: number;
  number: string;
  kind: string;
  kind_label: string;
  status: string;
  status_label: string;
  due_at: string;
  execute_after: string | null;
  outcome: string;
  created_at: string;
  download: boolean;
}
interface Privacy {
  consents: Record<string, boolean>;
  purposes: Record<string, string>;
  notice_version: string;
  retention: { data: string; kept_for: string; why: string }[];
  requests: DataRequest[];
  erasure_blockers: string[];
  response_days: number;
}

export function PrivacyCentre({ base }: { base: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["privacy"], queryFn: () => api.get<Privacy>("me/privacy/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["privacy"] });
  const consent = useMutation({ mutationFn: (body: { purpose: string; granted: boolean }) => api.post<Privacy>("me/privacy/", body), onSuccess: (d) => qc.setQueryData(["privacy"], d), onError: (e) => toast.error(errorText(e)) });
  const submit = useMutation({
    mutationFn: (body: { kind: string; details?: string }) => api.post<DataRequest>("me/privacy/requests/", body),
    onSuccess: (r) => {
      toast.success(t("Request {n} received", { n: r.number }));
      setDeleting(false);
      setCorrecting(false);
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const cancel = useMutation({ mutationFn: (id: number) => api.post(`me/privacy/requests/${id}/cancel/`), onSuccess: refresh });
  const [deleting, setDeleting] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [details, setDetails] = useState("");
  const p = q.data;
  if (!p) return null;
  const pendingErasure = p.requests.find((r) => r.kind === "ERASURE" && r.status === "WAITING");
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <Back to={`${base}/account`} label={t("Account")} />
      <h1 className="flex items-center gap-2 text-2xl font-bold">
        <ShieldCheck className="size-6" /> {t("Privacy")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("You decide what optional uses of your data are switched on. We answer every request within {n} days.", { n: p.response_days })}</p>

      <h2 className="mt-5 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Your choices")}</h2>
      {Object.entries(p.purposes).map(([purpose, label]) => (
        <div key={purpose} className="flex items-center gap-3 border-b border-line py-3">
          <span className="flex-1 text-sm font-medium">{t(label)}</span>
          <Toggle checked={!!p.consents[purpose]} onChange={(granted) => consent.mutate({ purpose, granted })} label={t(label)} />
        </div>
      ))}
      <p className="mt-2 text-xs text-muted">{t("Running your trips, payments and safety features doesn't need a toggle: it's how the service works. Notice version {v}.", { v: p.notice_version })}</p>

      <h2 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Your data")}</h2>
      <div className="grid gap-2">
        <Button variant="secondary" icon={<Download className="size-4" />} onClick={() => submit.mutate({ kind: "EXPORT" })} loading={submit.isPending}>
          {t("Download a copy of my data")}
        </Button>
        <Button variant="secondary" onClick={() => setCorrecting(true)}>
          {t("Correct something about me")}
        </Button>
        {pendingErasure ? (
          <div className="rounded-2xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
            {t("Your account will be deleted on {date}.", { date: dateTime(pendingErasure.execute_after) })}{" "}
            <button onClick={() => cancel.mutate(pendingErasure.id)} className="font-semibold underline">
              {t("Keep my account")}
            </button>
          </div>
        ) : (
          <Button variant="ghost" className="text-danger" icon={<Trash2 className="size-4" />} onClick={() => setDeleting(true)}>
            {t("Delete my account")}
          </Button>
        )}
      </div>

      {p.requests.length > 0 && (
        <>
          <h2 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Your requests")}</h2>
          {p.requests.map((r) => (
            <div key={r.id} className="flex items-center gap-2 border-b border-line py-2.5 text-sm">
              <span className="flex-1">
                <span className="font-semibold">{t(r.kind_label)}</span> <span className="text-xs text-muted">· {r.number}</span>
                <span className="block text-xs text-muted">
                  {t(r.status_label)}
                  {r.outcome && ` · ${r.outcome}`}
                </span>
              </span>
              {r.download && (
                <Button size="sm" variant="outline" icon={<Download className="size-3.5" />} onClick={() => openFile(`/api/v1/me/privacy/requests/${r.id}/download/`)}>
                  ZIP
                </Button>
              )}
            </div>
          ))}
        </>
      )}

      <h2 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("How long we keep things")}</h2>
      {p.retention.map((r) => (
        <div key={r.data} className="border-b border-line py-2 text-sm">
          <div className="flex justify-between gap-3">
            <span>{t(r.data)}</span>
            <span className="shrink-0 font-semibold">{t(r.kept_for)}</span>
          </div>
          <div className="text-xs text-muted">{t(r.why)}</div>
        </div>
      ))}

      <Modal open={deleting} onClose={() => setDeleting(false)} title={t("Delete your account?")} footer={<Button block variant="danger" disabled={p.erasure_blockers.length > 0} loading={submit.isPending} onClick={() => submit.mutate({ kind: "ERASURE" })}>{t("Delete in 7 days")}</Button>}>
        {p.erasure_blockers.length > 0 ? (
          <ul className="list-disc pl-5 text-sm text-danger">
            {p.erasure_blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">{t("Your name, phone, email, saved places, contacts and chats will be erased after 7 days (you can change your mind until then). Trip and payment records are kept without your name, because tax law requires it.")}</p>
        )}
      </Modal>
      <Modal open={correcting} onClose={() => setCorrecting(false)} title={t("What should we correct?")} footer={<Button block disabled={details.trim().length < 10} loading={submit.isPending} onClick={() => submit.mutate({ kind: "CORRECTION", details })}>{t("Send")}</Button>}>
        <Textarea rows={4} value={details} onChange={(e) => setDetails(e.target.value)} placeholder={t("For example: my name is spelt wrong on invoices")} />
      </Modal>
    </div>
  );
}

// --- Help centre -----------------------------------------------------------------------------

interface Article {
  id: number;
  slug: string;
  title: string;
  body: string;
  category: string;
}

export function HelpCentre({ base }: { base: string }) {
  const { slug } = useParams();
  const [query, setQuery] = useState("");
  const list = useQuery({ queryKey: ["help", query], queryFn: () => api.get<Article[]>(`help/?q=${encodeURIComponent(query)}`), enabled: !slug });
  const article = useQuery({ queryKey: ["help", "article", slug], queryFn: () => api.get<Article>(`help/${slug}/`), enabled: !!slug });
  const [voted, setVoted] = useState<boolean | null>(null);
  const vote = useMutation({ mutationFn: (helpful: boolean) => api.post(`help/${slug}/vote/`, { helpful }), onSuccess: (_d, helpful) => setVoted(helpful) });
  if (slug) {
    const a = article.data;
    return (
      <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
        <Back to={`${base}/help`} label={t("Help")} />
        {a && (
          <>
            <div className="text-xs font-semibold text-muted uppercase">{t(a.category)}</div>
            <h1 className="mt-1 text-xl font-bold">{t(a.title)}</h1>
            <p className="mt-3 text-sm leading-relaxed whitespace-pre-line">{t(a.body)}</p>
            <div className="mt-6 rounded-2xl bg-surface-2 p-3 text-sm">
              {voted === null ? (
                <div className="flex items-center gap-2">
                  <span className="flex-1">{t("Did this answer your question?")}</span>
                  <button onClick={() => vote.mutate(true)} className="rounded-full bg-surface p-2" aria-label={t("Yes")}>
                    <ThumbsUp className="size-4" />
                  </button>
                  <button onClick={() => vote.mutate(false)} className="rounded-full bg-surface p-2" aria-label={t("No")}>
                    <ThumbsDown className="size-4" />
                  </button>
                </div>
              ) : voted ? (
                <span>{t("Glad that helped!")}</span>
              ) : (
                <span>
                  {t("Sorry about that.")}{" "}
                  <Link to={`${base}/support`} className="font-semibold text-brand-strong">
                    {t("Talk to support")}
                  </Link>
                </span>
              )}
            </div>
          </>
        )}
      </div>
    );
  }
  const groups = (list.data ?? []).reduce<Record<string, Article[]>>((acc, a) => ({ ...acc, [a.category]: [...(acc[a.category] ?? []), a] }), {});
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <h1 className="text-2xl font-bold">{t("Help")}</h1>
      <div className="relative mt-3">
        <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("Search: refund, lost item, PIN…")} className="pl-9" />
      </div>
      {Object.entries(groups).map(([category, articles]) => (
        <div key={category} className="mt-5">
          <h2 className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{t(category)}</h2>
          {articles.map((a) => (
            <Link key={a.id} to={`${base}/help/${a.slug}`} className="block border-b border-line py-3 text-sm font-medium">
              {t(a.title)}
            </Link>
          ))}
        </div>
      ))}
      {!list.isLoading && !list.data?.length && <p className="mt-6 text-sm text-muted">{t("No articles match. Try other words, or talk to support.")}</p>}
      <div className="mt-6 grid grid-cols-2 gap-2">
        <Link to={`${base}/support`} className="rounded-2xl bg-surface-2 p-3 text-center text-sm font-semibold">
          {t("Talk to support")}
        </Link>
        <Link to={`${base}/claims`} className="rounded-2xl bg-surface-2 p-3 text-center text-sm font-semibold">
          {t("Insurance claims")}
        </Link>
      </div>
    </div>
  );
}

// --- Insurance claims ------------------------------------------------------------------------

interface Claim {
  id: number;
  number: string;
  trip_number: string;
  kind_label: string;
  status: string;
  status_label: string;
  amount_claimed: string;
  amount_approved: string | null;
  decision_note: string;
  created_at: string;
}

export function Claims({ base, trips }: { base: string; trips: { id: number; label: string }[] }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["claims"], queryFn: () => api.get<Claim[]>("me/claims/") });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ trip: "", kind: "PROPERTY", amount: "", description: "" });
  const [files, setFiles] = useState<FileList | null>(null);
  const file = useMutation({
    mutationFn: () => {
      const body = new FormData();
      Object.entries(form).forEach(([k, v]) => body.append(k, v));
      Array.from(files ?? []).forEach((f) => body.append("files", f));
      return api.post<Claim>("me/claims/", body);
    },
    onSuccess: (c) => {
      toast.success(t("Claim {n} filed", { n: c.number }));
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["claims"] });
    },
    onError: (e) => toast.error(errorText(e)),
  });
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <Back to={`${base}/help`} label={t("Help")} />
      <h1 className="flex items-center gap-2 text-2xl font-bold">
        <FileWarning className="size-6" /> {t("Insurance claims")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("Every ride includes accident cover. Claim within 7 days of the ride; approved amounts go to your wallet.")}</p>
      <Button className="mt-3" block onClick={() => setOpen(true)}>
        {t("File a claim")}
      </Button>
      {(q.data ?? []).map((c) => (
        <div key={c.id} className="mt-3 rounded-2xl border border-line p-3 text-sm">
          <div className="flex justify-between font-semibold">
            <span>
              {t(c.kind_label)} · {c.trip_number}
            </span>
            <span>{inr(c.amount_approved ?? c.amount_claimed, { whole: true })}</span>
          </div>
          <div className={clsx("text-xs", c.status === "PAID" ? "text-brand-strong" : c.status === "REJECTED" ? "text-danger" : "text-muted")}>
            {c.number} · {t(c.status_label)}
            {c.decision_note && ` · ${c.decision_note}`}
          </div>
        </div>
      ))}
      <Modal open={open} onClose={() => setOpen(false)} title={t("File a claim")} footer={<Button block loading={file.isPending} disabled={!form.trip || !form.amount || form.description.trim().length < 20} onClick={() => file.mutate()}>{t("Submit claim")}</Button>}>
        <Select value={form.trip} onChange={(e) => setForm({ ...form, trip: e.target.value })}>
          <option value="">{t("Which ride?")}</option>
          {trips.map((trip) => (
            <option key={trip.id} value={trip.id}>
              {trip.label}
            </option>
          ))}
        </Select>
        <Select className="mt-2" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          <option value="ACCIDENT">{t("Accident")}</option>
          <option value="INJURY">{t("Injury")}</option>
          <option value="PROPERTY">{t("Damaged belongings")}</option>
        </Select>
        <Input className="mt-2" inputMode="numeric" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/\\D/g, "") })} placeholder={t("Amount (₹)")} />
        <Textarea className="mt-2" rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder={t("What happened?")} />
        <input className="mt-2 text-xs" type="file" accept="image/*,application/pdf" multiple onChange={(e) => setFiles(e.target.files)} aria-label={t("Photos or bills")} />
      </Modal>
    </div>
  );
}

// --- Appeals ---------------------------------------------------------------------------------

interface Appeal {
  id: number;
  number: string;
  subject: string;
  subject_label: string;
  status: string;
  status_label: string;
  original_reason: string;
  decision_note: string;
  due_at: string;
}

export function Appeals({ base, subjects }: { base: string; subjects: { value: string; label: string }[] }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["appeals"], queryFn: () => api.get<Appeal[]>("me/appeals/") });
  const [subject, setSubject] = useState(subjects[0]?.value ?? "");
  const [statement, setStatement] = useState("");
  const send = useMutation({
    mutationFn: () => api.post<Appeal>("me/appeals/", { subject, statement }),
    onSuccess: (a) => {
      toast.success(t("Appeal {n} sent", { n: a.number }));
      setStatement("");
      qc.invalidateQueries({ queryKey: ["appeals"] });
    },
    onError: (e) => toast.error(errorText(e)),
  });
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <Back to={`${base}/account`} label={t("Account")} />
      <h1 className="flex items-center gap-2 text-2xl font-bold">
        <Gavel className="size-6" /> {t("Appeals")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("Think a decision about your account was wrong? Tell us why. Someone who didn't make the decision reviews it within 3 days.")}</p>
      <Select className="mt-3" value={subject} onChange={(e) => setSubject(e.target.value)}>
        {subjects.map((s) => (
          <option key={s.value} value={s.value}>
            {t(s.label)}
          </option>
        ))}
      </Select>
      <Textarea className="mt-2" rows={5} value={statement} onChange={(e) => setStatement(e.target.value)} placeholder={t("What happened, in your words")} />
      <Button className="mt-2" block disabled={statement.trim().length < 20} loading={send.isPending} onClick={() => send.mutate()}>
        {t("Send appeal")}
      </Button>
      {(q.data ?? []).map((a) => (
        <div key={a.id} className="mt-3 rounded-2xl border border-line p-3 text-sm">
          <div className="font-semibold">
            {t(a.subject_label)} · {a.number}
          </div>
          <div className="text-xs text-muted">{a.original_reason}</div>
          <div className={clsx("mt-1 text-xs font-semibold", a.status === "UPHELD" ? "text-brand-strong" : a.status === "DENIED" ? "text-danger" : "")}>{t(a.status_label)}</div>
          {a.decision_note && <div className="text-xs">{a.decision_note}</div>}
        </div>
      ))}
    </div>
  );
}

/** Claims with the person's recent rides to choose from. */
export function ClaimsPage({ base }: { base: string }) {
  const trips = useQuery({
    queryKey: ["trips", "recent-for-claims"],
    queryFn: () => api.get<{ results: { id: number; trip_number: string; status: string; dropoff_address: string; requested_at: string }[] }>("trips/?page_size=20"),
  });
  const options = (trips.data?.results ?? [])
    .filter((trip) => ["COMPLETED", "IN_PROGRESS", "CANCELLED"].includes(trip.status))
    .map((trip) => ({ id: trip.id, label: `${trip.trip_number} · ${trip.dropoff_address} · ${dateTime(trip.requested_at)}` }));
  return <Claims base={base} trips={options} />;
}

export const RIDER_APPEALS = [
  { value: "RIDER_BLOCK", label: "My account was blocked" },
  { value: "FRAUD_DECISION", label: "A fraud decision about me" },
];
export const DRIVER_APPEALS = [
  { value: "DRIVER_SUSPENSION", label: "My driver account was suspended" },
  { value: "FRAUD_DECISION", label: "A fraud decision about me" },
];

interface Grievance {
  id: number;
  number: string;
  category_label: string;
  subject: string;
  status: string;
  status_label: string;
  created_at: string;
  ack_due: string;
  resolve_due: string;
  acknowledged_at: string | null;
  resolution: string;
  escalated_at: string | null;
  satisfied: boolean | null;
}
interface Officer {
  name: string;
  title: string;
  email: string;
  phone: string;
  hours: string;
  address: string;
}

const GRIEVANCE_CATEGORIES = [
  ["FARE", "Fare or charges"],
  ["CONDUCT", "Conduct of a driver or rider"],
  ["SAFETY", "Safety"],
  ["ACCOUNT", "Account suspended or blocked"],
  ["EARNINGS", "Earnings, commission or payouts"],
  ["DISCRIM", "Discrimination"],
  ["SERVICE", "Service quality"],
  ["OTHER", "Something else"],
] as const;

/** The formal grievance route (Aggregator Guidelines): acknowledged in 48 h, resolved in 15 days. */
export function Grievances({ base }: { base: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["grievances"], queryFn: () => api.get<{ officer: Officer; grievances: Grievance[] }>("me/grievances/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["grievances"] });
  const [category, setCategory] = useState("FARE");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [escalating, setEscalating] = useState<Grievance | null>(null);
  const [reason, setReason] = useState("");
  const send = useMutation({
    mutationFn: () => api.post<Grievance>("me/grievances/", { category, subject, description }),
    onSuccess: (g) => {
      toast.success(t("Grievance {n} received", { n: g.number }));
      setSubject("");
      setDescription("");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const escalate = useMutation({
    mutationFn: () => api.post(`me/grievances/${escalating!.id}/escalate/`, { reason }),
    onSuccess: () => { setEscalating(null); setReason(""); refresh(); },
    onError: (e) => toast.error(errorText(e)),
  });
  const rate = useMutation({ mutationFn: (g: Grievance) => api.post(`me/grievances/${g.id}/rate/`, { satisfied: true }), onSuccess: refresh });
  const o = q.data?.officer;
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-8">
      <Back to={`${base}/account`} label={t("Account")} />
      <h1 className="flex items-center gap-2 text-2xl font-bold">
        <Scale className="size-6" /> {t("Grievances")}
      </h1>
      <p className="mt-1 text-sm text-muted">{t("Not happy with how something was handled? Our grievance officer acknowledges every grievance within 48 hours and answers in writing within 15 days.")}</p>
      {o && (
        <div className="mt-3 rounded-2xl bg-surface-2 p-3 text-xs">
          <div className="font-semibold">{o.name} · {t("Grievance officer")}</div>
          <div>{o.email} · {o.phone}</div>
          <div className="text-muted">{o.hours}</div>
        </div>
      )}
      <Select className="mt-3" value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t("What is it about?")}>
        {GRIEVANCE_CATEGORIES.map(([value, label]) => (
          <option key={value} value={value}>{t(label)}</option>
        ))}
      </Select>
      <Input className="mt-2" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={140} placeholder={t("Short title")} aria-label={t("Short title")} />
      <Textarea className="mt-2" rows={5} value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t("What happened, in your words")} aria-label={t("What happened, in your words")} />
      <Button className="mt-2" block disabled={subject.trim().length < 5 || description.trim().length < 20} loading={send.isPending} onClick={() => send.mutate()}>
        {t("Send to the grievance officer")}
      </Button>
      {(q.data?.grievances ?? []).map((g) => (
        <div key={g.id} className="mt-3 rounded-2xl border border-line p-3 text-sm">
          <div className="font-semibold">{g.subject} · {g.number}</div>
          <div className="text-xs text-muted">{t(g.category_label)} · {dateTime(g.created_at)}</div>
          <div className="mt-1 text-xs font-semibold">{t(g.status_label)}</div>
          {!g.acknowledged_at && g.status === "RECEIVED" && <div className="text-xs text-muted">{t("Acknowledgement due by {when}", { when: dateTime(g.ack_due) })}</div>}
          {["RECEIVED", "ACKNOWLEDGED", "ESCALATED"].includes(g.status) && <div className="text-xs text-muted">{t("Answer due by {when}", { when: dateTime(g.resolve_due) })}</div>}
          {g.resolution && <div className="mt-1 rounded-xl bg-surface-2 p-2 text-xs">{g.resolution}</div>}
          {g.status === "RESOLVED" && g.satisfied === null && (
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => rate.mutate(g)}>{t("I'm satisfied")}</Button>
              <Button size="sm" variant="ghost" onClick={() => setEscalating(g)}>{t("Escalate")}</Button>
            </div>
          )}
          {g.escalated_at && <div className="mt-1 text-xs text-muted">{t("With the appellate officer. You may also approach your state transport authority or the consumer commission.")}</div>}
        </div>
      ))}
      <Modal open={!!escalating} onClose={() => setEscalating(null)} title={t("Escalate to the appellate officer")}>
        <Textarea rows={4} value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("Why isn't the answer right?")} aria-label={t("Why isn't the answer right?")} />
        <Button className="mt-3" block disabled={reason.trim().length < 10} loading={escalate.isPending} onClick={() => escalate.mutate()}>{t("Escalate")}</Button>
      </Modal>
    </div>
  );
}
