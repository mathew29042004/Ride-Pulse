/** Ops → Announcements: write once (English, plus Tamil and Hindi if you like), choose who and
 * where, and see how many have read it. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Megaphone } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Input, PageHeader, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { City } from "@/lib/types";

interface Row {
  id: number;
  title: string;
  body: string;
  languages: string[];
  audience_label: string;
  where: string;
  important: boolean;
  published_at: string;
  recipients: number;
  read: number;
  read_rate: number | null;
  by: string | null;
}

const LANGS = [
  ["en", "English"],
  ["ta", "தமிழ்"],
  ["hi", "हिन्दी"],
] as const;

export default function OpsAnnouncements() {
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["announcements"], queryFn: () => api.get<Row[]>("announcements/") });
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/") });
  const [lang, setLang] = useState<"en" | "ta" | "hi">("en");
  const [text, setText] = useState<Record<string, { title: string; body: string }>>({ en: { title: "", body: "" }, ta: { title: "", body: "" }, hi: { title: "", body: "" } });
  const [audience, setAudience] = useState("DRIVERS");
  const [where, setWhere] = useState("");
  const [important, setImportant] = useState(false);
  const states = [...new Set((cities.data ?? []).map((c) => c.state))].sort();
  const publish = useMutation({
    mutationFn: () =>
      api.post<{ recipients: number }>("announcements/", {
        audience,
        important,
        text,
        ...(where.startsWith("city:") ? { city: where.slice(5) } : { state: where }),
      }),
    onSuccess: (r) => {
      toast.success(`Sent to ${r.recipients.toLocaleString("en-IN")} people`);
      setText({ en: { title: "", body: "" }, ta: { title: "", body: "" }, hi: { title: "", body: "" } });
      qc.invalidateQueries({ queryKey: ["announcements"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't send."),
  });
  const part = text[lang];
  return (
    <>
      <PageHeader title="Announcements" subtitle="Reach drivers, riders or staff in one go, in their own language, and see who has read it." />
      <div className="grid gap-4 lg:grid-cols-[420px_1fr]">
        <Card className="p-4">
          <CardHeader title="New announcement" />
          <div className="grid grid-cols-2 gap-2">
            <select value={audience} onChange={(e) => setAudience(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="Audience">
              <option value="DRIVERS">Drivers</option>
              <option value="RIDERS">Riders</option>
              <option value="STAFF">Staff</option>
            </select>
            <select value={where} onChange={(e) => setWhere(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="Where">
              <option value="">Everywhere</option>
              {states.map((s) => (
                <optgroup key={s} label={s}>
                  <option value={s}>All of {s}</option>
                  {(cities.data ?? [])
                    .filter((c) => c.state === s)
                    .map((c) => (
                      <option key={c.slug} value={`city:${c.slug}`}>
                        {c.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="mt-3 flex gap-1">
            {LANGS.map(([code, label]) => (
              <button key={code} onClick={() => setLang(code)} className={clsx("rounded-full px-3 py-1 text-xs font-semibold", lang === code ? "bg-ink text-ink-fg" : "bg-surface-2")}>
                {label}
                {code !== "en" && text[code].title && " ✓"}
              </button>
            ))}
          </div>
          <Input className="mt-2" value={part.title} onChange={(e) => setText({ ...text, [lang]: { ...part, title: e.target.value } })} placeholder={lang === "en" ? "Title (required)" : "Title (optional translation)"} />
          <Textarea className="mt-2" rows={4} value={part.body} onChange={(e) => setText({ ...text, [lang]: { ...part, body: e.target.value } })} placeholder="Message" />
          <label className="mt-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={important} onChange={(e) => setImportant(e.target.checked)} /> Important (pinned on their home screen until read)
          </label>
          <p className="mt-1 text-xs text-muted">People whose app is in a language you didn't fill in see the English version.</p>
          <Button className="mt-3" block icon={<Megaphone className="size-4" />} loading={publish.isPending} disabled={!text.en.title || !text.en.body} onClick={() => publish.mutate()}>
            Send
          </Button>
        </Card>
        <Card className="p-4">
          <CardHeader title="Sent" />
          <div className="divide-y divide-line">
            {(rows.data ?? []).map((r) => (
              <div key={r.id} className="py-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{r.title}</span>
                  {r.important && <Badge tone="warning">Important</Badge>}
                  <span className="ml-auto text-xs text-muted">{dateTime(r.published_at)}</span>
                </div>
                <div className="text-xs text-muted">
                  {r.audience_label} · {r.where} · {r.languages.join(", ")} · {r.by}
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs">
                  <div className="h-1.5 flex-1 rounded-full bg-surface-3">
                    <div className="h-full rounded-full bg-brand" style={{ width: `${Math.round((r.read_rate ?? 0) * 100)}%` }} />
                  </div>
                  read by {r.read.toLocaleString("en-IN")} of {r.recipients.toLocaleString("en-IN")} ({Math.round((r.read_rate ?? 0) * 100)}%)
                </div>
              </div>
            ))}
            {rows.data?.length === 0 && <p className="text-sm text-muted">Nothing sent yet.</p>}
          </div>
        </Card>
      </div>
    </>
  );
}
