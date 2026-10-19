/** Ops → Backups: nightly database backups and the weekly restore drill (restore the latest
 * backup into a scratch database, compare row counts, check the ledger balances, time it). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";

import { Badge, Button, Card, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useAuth } from "@/lib/auth";

interface Run {
  id: number;
  kind: "BACKUP" | "DRILL";
  kind_label: string;
  started_at: string;
  seconds: number;
  ok: boolean;
  file_name: string;
  size_bytes: number;
  sha256: string;
  details: { checks?: { check: string; ok: boolean; detail: string }[]; restore_seconds?: number };
  error: string;
  by: string;
}
interface Overview {
  backup_dir: string;
  keep: number;
  last_backup_hours: number | null;
  last_drill_ok: boolean | null;
  last_restore_seconds: number | null;
  runs: Run[];
}

const mb = (b: number) => `${(b / 1e6).toFixed(1)} MB`;

export default function OpsBackups() {
  const qc = useQueryClient();
  const canRun = useAuth().can("users.manage");
  const q = useQuery({ queryKey: ["ops", "backups"], queryFn: () => api.get<Overview>("ops/backups/") });
  const set = (data: Overview) => qc.setQueryData(["ops", "backups"], data);
  const backup = useMutation({ mutationFn: () => api.post<Overview>("ops/backups/run/"), onSuccess: set });
  const drill = useMutation({ mutationFn: () => api.post<Overview>("ops/backups/drill/"), onSuccess: set });
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Backups"
        subtitle={`Backed up every night at 2:30 am (newest ${d?.keep ?? 14} kept in ${d?.backup_dir ?? "backups/"}). Every Sunday the restore drill restores the latest one into a scratch database and checks it.`}
        actions={
          canRun && (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" loading={backup.isPending} onClick={() => backup.mutate()}>Back up now</Button>
              <Button size="sm" loading={drill.isPending} onClick={() => drill.mutate()}>Run restore drill</Button>
            </div>
          )
        }
      />
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Card className="p-3"><Stat label="Last backup" value={d?.last_backup_hours == null ? "Never" : `${d.last_backup_hours} h ago`} /></Card>
        <Card className="p-3"><Stat label="Last drill" value={d?.last_drill_ok == null ? "Never" : d.last_drill_ok ? "Passed" : "Failed"} /></Card>
        <Card className="p-3"><Stat label="Time to restore" value={d?.last_restore_seconds != null ? `${d.last_restore_seconds} s` : "—"} /></Card>
      </div>
      <div className="space-y-2">
        {d?.runs.map((r) => (
          <Card key={r.id} className="p-3 text-sm">
            <div className="flex items-center gap-2">
              {r.ok ? <CheckCircle2 className="size-4 text-brand" /> : <XCircle className="size-4 text-danger" />}
              <Badge tone={r.kind === "DRILL" ? "brand" : "neutral"}>{r.kind_label}</Badge>
              <span className="font-semibold">{dateTime(r.started_at)}</span>
              <span className="text-xs text-muted">{r.seconds}s · {r.by}</span>
            </div>
            {r.kind === "BACKUP" && r.ok && <div className="mt-1 text-xs text-muted">{r.file_name} · {mb(r.size_bytes)} · sha256 {r.sha256}…</div>}
            {r.error && <div className="mt-1 text-xs text-danger">{r.error}</div>}
            {r.details.checks && (
              <div className="mt-2 grid gap-x-4 text-xs sm:grid-cols-2">
                {r.details.checks.map((c) => (
                  <div key={c.check} className={c.ok ? "" : "text-danger"}>
                    {c.ok ? "✓" : "✗"} {c.check} <span className="text-muted">{c.detail}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
