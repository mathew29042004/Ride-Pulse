/** Ops → NPS: riders' and drivers' likelihood to recommend us, by city and month, with what
 * detractors and promoters talk about (keyword themes, not AI). */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";

import { Card, CardHeader, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";

interface Part {
  responses: number;
  nps: number | null;
  promoters: number;
  passives: number;
  detractors: number;
  by_city: { city: string; nps: number; responses: number }[];
  by_month: { month: string; nps: number; responses: number }[];
  detractor_themes: { theme: string; mentions: number }[];
  promoter_themes: { theme: string; mentions: number }[];
  recent_comments: { score: number; comment: string; city: string }[];
}

const tone = (n: number | null) => (n == null ? "" : n >= 30 ? "text-brand" : n >= 0 ? "text-amber-600" : "text-danger");

export default function OpsNps() {
  const q = useQuery({ queryKey: ["nps", "report"], queryFn: () => api.get<Record<"RIDER" | "DRIVER", Part>>("nps/report/") });
  return (
    <>
      <PageHeader title="NPS" subtitle="“How likely are you to recommend Ride Pulse?” (0–10), asked every 90 days after a few trips. NPS = % promoters (9–10) − % detractors (0–6), last 90 days. Themes come from keyword rules, not AI." />
      <div className="grid gap-4 lg:grid-cols-2">
        {(["RIDER", "DRIVER"] as const).map((key) => {
          const p = q.data?.[key];
          if (!p) return null;
          return (
            <Card key={key} className="p-4">
              <CardHeader title={key === "RIDER" ? "Riders" : "Drivers"} />
              <div className="grid grid-cols-3 gap-2">
                <Stat label="NPS" value={<span className={tone(p.nps)}>{p.nps ?? "—"}</span>} sub={`${p.responses} answers`} />
                <Stat label="Promoters" value={p.promoters} />
                <Stat label="Detractors" value={p.detractors} />
              </div>
              <div className="mt-3 flex items-end gap-2">
                {p.by_month.map((m) => (
                  <div key={m.month} className="flex-1 text-center text-xs">
                    <div className={clsx("font-bold", tone(m.nps))}>{m.nps}</div>
                    <div className="text-muted">{m.month.slice(5)}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="mb-1 font-semibold">Detractors mention</div>
                  {p.detractor_themes.slice(0, 5).map((t) => (
                    <div key={t.theme} className="flex justify-between">
                      {t.theme} <span className="text-muted">{t.mentions}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div className="mb-1 font-semibold">Promoters mention</div>
                  {p.promoter_themes.slice(0, 5).map((t) => (
                    <div key={t.theme} className="flex justify-between">
                      {t.theme} <span className="text-muted">{t.mentions}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-3 text-xs">
                <div className="mb-1 font-semibold">Lowest cities</div>
                {p.by_city.slice(0, 5).map((c) => (
                  <div key={c.city} className="flex justify-between">
                    {c.city} <span className={tone(c.nps)}>{c.nps} ({c.responses})</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 space-y-1 text-xs">
                <div className="font-semibold">Recent comments</div>
                {p.recent_comments.slice(0, 6).map((c, i) => (
                  <div key={i} className="rounded-lg bg-surface-2 p-2">
                    <b className={tone(c.score >= 9 ? 50 : c.score <= 6 ? -1 : 10)}>{c.score}</b> · {c.city}: {c.comment}
                  </div>
                ))}
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
