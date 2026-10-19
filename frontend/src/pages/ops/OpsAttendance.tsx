/** Ops → Attendance: clock in and out (matched to your roster shift, or office hours 9:30–6:30),
 * your month, corrections; managers see their team's board and approve corrections. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Input, Modal, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

interface Row {
  id: number;
  name: string;
  day: string;
  shift: string;
  expected_start: string;
  expected_end: string;
  clock_in: string | null;
  clock_out: string | null;
  status: string;
  status_label: string;
  late_minutes: number;
  worked_minutes: number;
  correction: { status: string; reason: string } | null;
}
interface Summary {
  present: number;
  late: number;
  half_day: number;
  absent: number;
  on_leave: number;
  no_clock_out: number;
  avg_hours: number | null;
}
interface Mine {
  working: Row | null;
  next: { shift: string; starts: string; ends: string };
  month: Summary;
  records: Row[];
}
interface Team {
  in_now: number;
  late_today: number;
  people: { user_id: number; name: string; rostered: boolean; today: Row | null; month: Summary }[];
  corrections: Row[];
}

const hm = (s: string | null) => (s ? new Date(s).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—");
const tone = (s: string) => (s === "PRESENT" || s === "WORKING" ? "brand" : s === "ABSENT" || s === "NO_OUT" ? "danger" : s === "ON_LEAVE" ? "neutral" : "warning");
const local = (s: string) => s.slice(0, 16);

export default function OpsAttendance() {
  const qc = useQueryClient();
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const mine = useQuery({ queryKey: ["attendance", "mine"], queryFn: () => api.get<Mine>("work/attendance/") });
  const team = useQuery({ queryKey: ["attendance", "team"], queryFn: () => api.get<Team>("work/attendance/team/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["attendance"] });
  const clockIn = useMutation({ mutationFn: () => api.post<Mine>("work/attendance/clock-in/"), onSuccess: refresh, onError: fail });
  const clockOut = useMutation({ mutationFn: () => api.post<Mine>("work/attendance/clock-out/"), onSuccess: refresh, onError: fail });
  const decide = useMutation({ mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post(`work/attendance/${id}/decide/`, { approve }), onSuccess: refresh, onError: fail });
  const [fixing, setFixing] = useState<Row | null>(null);
  const [fixIn, setFixIn] = useState("");
  const [fixOut, setFixOut] = useState("");
  const [reason, setReason] = useState("");
  const correct = useMutation({
    mutationFn: () => api.post(`work/attendance/${fixing!.id}/correct/`, { clock_in: fixIn ? new Date(fixIn).toISOString() : null, clock_out: fixOut ? new Date(fixOut).toISOString() : null, reason }),
    onSuccess: () => { toast.success("Sent to your manager."); setFixing(null); refresh(); },
    onError: fail,
  });
  const m = mine.data;
  const t = team.data;
  return (
    <>
      <PageHeader title="Attendance" subtitle="Clock in from 30 minutes before your shift (or office hours, 9:30–6:30). More than 10 minutes after the start is late; under 4 hours is a half day. Approved leave never counts as absent." />
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="p-4">
          <div className="flex items-center gap-2 text-sm text-muted"><Clock className="size-4" /> {m?.next.shift} · {hm(m?.next.starts ?? null)}–{hm(m?.next.ends ?? null)}</div>
          {m?.working ? (
            <>
              <div className="mt-2 text-lg font-bold">Clocked in at {hm(m.working.clock_in)}</div>
              {m.working.late_minutes > 0 && <div className="text-sm text-amber-600">{m.working.late_minutes} min late</div>}
              <Button className="mt-3" block variant="secondary" loading={clockOut.isPending} onClick={() => clockOut.mutate()}>Clock out</Button>
            </>
          ) : (
            <Button className="mt-3" block loading={clockIn.isPending} onClick={() => clockIn.mutate()}>Clock in</Button>
          )}
          {m && (
            <div className="mt-4 grid grid-cols-3 gap-2">
              <Stat label="Present" value={m.month.present} />
              <Stat label="Late" value={m.month.late} />
              <Stat label="Absent" value={m.month.absent} />
              <Stat label="Half days" value={m.month.half_day} />
              <Stat label="Leave" value={m.month.on_leave} />
              <Stat label="Avg hours" value={m.month.avg_hours ?? "—"} />
            </div>
          )}
          <div className="mt-4 space-y-1 text-xs">
            {m?.records.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-2">
                <span>{r.day} · {hm(r.clock_in)}–{hm(r.clock_out)}</span>
                <span className="flex items-center gap-1">
                  <Badge tone={tone(r.status)}>{r.status_label}</Badge>
                  {r.correction?.status === "PENDING" ? <span className="text-muted">correction sent</span> : r.status !== "WORKING" && (
                    <button className="text-brand" onClick={() => { setFixing(r); setFixIn(local(r.clock_in ?? r.expected_start)); setFixOut(local(r.clock_out ?? r.expected_end)); setReason(""); }}>Fix</button>
                  )}
                </span>
              </div>
            ))}
          </div>
        </Card>
        {t && t.people.length > 0 && (
          <Card className="overflow-x-auto p-4">
            <CardHeader title="My team today" subtitle={`${t.in_now} clocked in now · ${t.late_today} late today`} />
            {t.corrections.length > 0 && (
              <div className="mb-3 space-y-1">
                {t.corrections.map((c) => (
                  <div key={c.id} className="flex items-center justify-between rounded-xl bg-surface-2 p-2 text-sm">
                    <span><b>{c.name}</b> · {c.day}: “{c.correction?.reason}”</span>
                    <span className="flex gap-1">
                      <Button size="sm" onClick={() => decide.mutate({ id: c.id, approve: true })}>Approve</Button>
                      <Button size="sm" variant="secondary" onClick={() => decide.mutate({ id: c.id, approve: false })}>Decline</Button>
                    </span>
                  </div>
                ))}
              </div>
            )}
            <Table>
              <thead><tr><Th>Name</Th><Th>Today</Th><Th>In</Th><Th>Out</Th><Th>Present</Th><Th>Late</Th><Th>Absent</Th><Th>Leave</Th><Th>Avg h</Th></tr></thead>
              <tbody>
                {t.people.map((p) => (
                  <tr key={p.user_id}>
                    <Td>{p.name}</Td>
                    <Td>{p.today ? <Badge tone={tone(p.today.status)}>{p.today.status_label}</Badge> : <span className="text-xs text-muted">{p.rostered ? "Not in yet" : "Not rostered"}</span>}</Td>
                    <Td>{hm(p.today?.clock_in ?? null)}</Td>
                    <Td>{hm(p.today?.clock_out ?? null)}</Td>
                    <Td>{p.month.present}</Td>
                    <Td>{p.month.late}</Td>
                    <Td className={p.month.absent ? "text-danger" : ""}>{p.month.absent}</Td>
                    <Td>{p.month.on_leave}</Td>
                    <Td>{p.month.avg_hours ?? "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </div>
      <Modal open={!!fixing} onClose={() => setFixing(null)} title={`Correct ${fixing?.day ?? ""}`}>
        <div className="space-y-2 text-sm">
          <label className="block">Clock in<Input type="datetime-local" value={fixIn} onChange={(e) => setFixIn(e.target.value)} /></label>
          <label className="block">Clock out<Input type="datetime-local" value={fixOut} onChange={(e) => setFixOut(e.target.value)} /></label>
          <label className="block">Reason<Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} placeholder="e.g. Forgot to clock out after the night shift" /></label>
          <Button block disabled={reason.trim().length < 5} loading={correct.isPending} onClick={() => correct.mutate()}>Send to my manager</Button>
        </div>
      </Modal>
    </>
  );
}
