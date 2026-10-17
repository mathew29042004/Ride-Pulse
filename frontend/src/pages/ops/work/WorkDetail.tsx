/** One task (progress, check-ins, guidance) and one meeting (RSVP, notes, action items). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, CalendarClock, MessageCircleQuestion, Plus, Repeat, Send, Trash2, MessagesSquare } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Field, Input, KeyValue, PageHeader, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";

import { localInput, type Meeting, type Person, PRIORITY_TONE, toIso, type WorkTask } from "./api";
import { TaskRow } from "./OpsWork";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");

function Back() {
  return (
    <Link to="/ops/work" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
      <ArrowLeft className="size-4" /> Work
    </Link>
  );
}

/** Opens (and joins) the conversation on this task or meeting in Team chat. */
function DiscussButton({ target }: { target: { task_id: number } | { meeting_id: number } }) {
  const navigate = useNavigate();
  const open = useMutation({
    mutationFn: () => api.post<{ id: number }>("chat/thread/", target),
    onSuccess: (r) => navigate(`/ops/chat/${r.id}`),
  });
  return (
    <Button size="sm" variant="outline" icon={<MessagesSquare className="size-4" />} loading={open.isPending} onClick={() => open.mutate()}>
      Discuss
    </Button>
  );
}

export function WorkTaskPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const key = ["work", "task", id];
  const task = useQuery({ queryKey: key, queryFn: () => api.get<WorkTask>(`work/tasks/${id}/`), refetchInterval: 10_000 });
  const people = useQuery({ queryKey: ["work", "people"], queryFn: () => api.get<Person[]>("work/people/") });
  const [note, setNote] = useState("");
  const [progress, setProgress] = useState("");
  const [due, setDue] = useState(localInput(24));
  const done = (data: WorkTask) => {
    qc.setQueryData(key, data);
    qc.invalidateQueries({ queryKey: ["work", "tasks"] });
    setNote("");
    setProgress("");
  };
  const onError = (err: unknown) => toast.error(errorText(err));
  const usePost = (path: string) => useMutation({ mutationFn: (body: object) => api.post<WorkTask>(`work/tasks/${id}/${path}/`, body), onSuccess: done, onError });
  const update = usePost("update_status");
  const comment = usePost("comment");
  const ask = usePost("ask_status");
  const manage = usePost("manage");

  const t = task.data;
  if (!t) return <Back />;
  const open = t.status === "TODO" || t.status === "IN_PROGRESS";
  const canManage = !t.mine || t.assigned_by === t.assignee;

  return (
    <>
      <Back />
      <PageHeader
        title={t.title}
        subtitle={`${t.number} · from ${t.assigned_by_name} to ${t.assignee_name}`}
        actions={
          <div className="flex gap-2">
            <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority_label}</Badge>
            <Badge tone={t.is_overdue ? "danger" : t.status === "DONE" ? "brand" : "neutral"}>{t.is_overdue ? "Overdue" : t.status_label}</Badge>
            <DiscussButton target={{ task_id: t.id }} />
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="p-4">
          {t.description && <p className="mb-4 text-sm whitespace-pre-line">{t.description}</p>}
          {t.target ? (
            <div className="mb-4">
              <div className="mb-1 flex justify-between text-xs text-muted">
                <span>Progress</span>
                <span>
                  {t.progress} / {t.target}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(100, (100 * t.progress) / t.target)}%` }} />
              </div>
            </div>
          ) : null}
          <CardHeader title="Check-ins" />
          <div className="space-y-2">
            {(t.comments ?? []).map((c) => (
              <div
                key={c.id}
                className={clsx(
                  "rounded-xl px-3 py-2 text-sm",
                  c.kind === "SYSTEM" ? "text-xs text-muted" : c.kind === "STATUS_REQUEST" ? "bg-amber-50 dark:bg-amber-400/10" : "bg-surface-2",
                )}
              >
                {c.kind !== "SYSTEM" && <span className="font-semibold">{c.author_name}: </span>}
                {c.body}
                <span className="ml-2 text-[11px] text-muted">{dateTime(c.created_at)}</span>
              </div>
            ))}
          </div>
          {open && (
            <div className="mt-3 flex gap-2">
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t.mine ? "Post an update or ask a question" : "Give guidance"} />
              <Button icon={<Send className="size-4" />} disabled={!note.trim()} loading={comment.isPending} onClick={() => comment.mutate({ body: note })}>
                Send
              </Button>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card className="p-4">
            <KeyValue label="Due">{dateTime(t.due_at)}</KeyValue>
            {t.started_at && <KeyValue label="Started">{dateTime(t.started_at)}</KeyValue>}
            {t.completed_at && <KeyValue label="Finished">{dateTime(t.completed_at)}</KeyValue>}
            {t.meeting && (
              <KeyValue label="From meeting">
                <Link className="text-brand-strong" to={`/ops/work/meetings/${t.meeting}`}>
                  {t.meeting_title}
                </Link>
              </KeyValue>
            )}
          </Card>

          {open && t.mine && (
            <Card className="space-y-2 p-4">
              <CardHeader title="Your update" />
              {t.target ? (
                <div className="flex gap-2">
                  <Input type="number" min={0} value={progress} onChange={(e) => setProgress(e.target.value)} placeholder={`Done so far (of ${t.target})`} />
                  <Button variant="secondary" disabled={progress === ""} onClick={() => update.mutate({ progress: Number(progress), note })}>
                    Save
                  </Button>
                </div>
              ) : null}
              {t.status === "TODO" && (
                <Button block variant="secondary" onClick={() => update.mutate({ status: "IN_PROGRESS", note })}>
                  Start
                </Button>
              )}
              <Button block onClick={() => update.mutate({ status: "DONE", note })} loading={update.isPending}>
                Mark done
              </Button>
            </Card>
          )}

          {open && canManage && (
            <Card className="space-y-2 p-4">
              <CardHeader title="Manage" />
              <Button block variant="outline" icon={<MessageCircleQuestion className="size-4" />} disabled={t.awaiting_update} onClick={() => ask.mutate({})}>
                {t.awaiting_update ? "Waiting for their update" : "Ask for a status update"}
              </Button>
              <Field label="Move deadline">
                <div className="flex gap-2">
                  <Input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
                  <Button variant="secondary" disabled={!due} onClick={() => manage.mutate({ due_at: toIso(due) })}>
                    Move
                  </Button>
                </div>
              </Field>
              <Field label="Give to someone else">
                <Select defaultValue="" onChange={(e) => e.target.value && manage.mutate({ assignee_id: Number(e.target.value) })}>
                  <option value="">Choose…</option>
                  {(people.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.title}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button block variant="ghost" className="text-danger" onClick={() => manage.mutate({ cancel: true })}>
                Cancel task
              </Button>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

export function WorkMeetingPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { user } = useAuth();
  const key = ["work", "meeting", id];
  const meeting = useQuery({ queryKey: key, queryFn: () => api.get<Meeting>(`work/meetings/${id}/`), refetchInterval: 15_000 });
  const [notes, setNotes] = useState("");
  const [present, setPresent] = useState<number[] | null>(null);
  const [items, setItems] = useState<{ title: string; assignee_id: string; due: string }[]>([]);
  const done = (data: Meeting) => {
    qc.setQueryData(key, data);
    qc.invalidateQueries({ queryKey: ["work"] });
  };
  const onError = (err: unknown) => toast.error(errorText(err));
  const respond = useMutation({ mutationFn: (accept: boolean) => api.post<Meeting>(`work/meetings/${id}/respond/`, { accept }), onSuccess: done, onError });
  const cancel = useMutation({ mutationFn: (whole_series: boolean) => api.post<Meeting>(`work/meetings/${id}/cancel/`, { whole_series }), onSuccess: done, onError });
  const complete = useMutation({
    mutationFn: () =>
      api.post<Meeting>(`work/meetings/${id}/complete/`, {
        notes,
        present_ids: present ?? undefined,
        action_items: items.filter((i) => i.title.trim() && i.assignee_id).map((i) => ({ title: i.title, assignee_id: Number(i.assignee_id), due_at: toIso(i.due) })),
      }),
    onSuccess: (data) => {
      done(data);
      toast.success("Meeting notes saved; action items sent as tasks");
    },
    onError,
  });

  const m = meeting.data;
  if (!m) return <Back />;
  const organiser = m.organizer === user?.id;
  const scheduled = m.status === "SCHEDULED";
  const others = m.attendees.filter((a) => a.user !== m.organizer);
  const presentIds = present ?? others.filter((a) => a.response === "ACCEPTED").map((a) => a.user);

  return (
    <>
      <Back />
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {m.title} {m.repeats_daily && <Repeat className="size-5 text-muted" aria-label="Daily" />}
          </span>
        }
        subtitle={`${dateTime(m.starts_at)} · ${m.duration_minutes} min · organised by ${m.organizer_name}`}
        actions={
          <div className="flex gap-2">
            <Badge tone={m.status === "DONE" ? "brand" : m.status === "CANCELLED" ? "danger" : "neutral"}>{m.status_label}</Badge>
            <DiscussButton target={{ meeting_id: m.id }} />
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {m.agenda && (
            <Card className="p-4">
              <CardHeader title="Agenda" />
              <p className="text-sm whitespace-pre-line">{m.agenda}</p>
            </Card>
          )}
          {m.status === "DONE" && (
            <Card className="p-4">
              <CardHeader title="Notes" />
              <p className="text-sm whitespace-pre-line">{m.notes || "No notes."}</p>
              {m.action_items.length > 0 && (
                <div className="mt-4 space-y-2">
                  <div className="text-xs font-semibold text-muted uppercase">Action items</div>
                  {m.action_items.map((t) => (
                    <TaskRow key={t.id} task={t} />
                  ))}
                </div>
              )}
            </Card>
          )}
          {organiser && scheduled && (
            <Card className="p-4">
              <CardHeader title="Write up the meeting" subtitle="Notes go to everyone invited; each action item becomes a task." />
              <Textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What was discussed and decided" />
              <div className="mt-3 space-y-2">
                {items.map((item, i) => (
                  <div key={i} className="flex flex-wrap gap-2">
                    <Input className="min-w-48 flex-1" value={item.title} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} placeholder="Action item" />
                    <Select className="!w-44" value={item.assignee_id} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, assignee_id: e.target.value } : x)))}>
                      <option value="">Who?</option>
                      {others.map((a) => (
                        <option key={a.user} value={a.user}>
                          {a.name}
                        </option>
                      ))}
                    </Select>
                    <Input type="datetime-local" className="!w-52" value={item.due} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, due: e.target.value } : x)))} />
                    <button onClick={() => setItems(items.filter((_, j) => j !== i))} className="p-2 text-muted hover:text-danger" aria-label="Remove">
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                ))}
                <Button variant="ghost" size="sm" icon={<Plus className="size-4" />} onClick={() => setItems([...items, { title: "", assignee_id: "", due: localInput(24) }])}>
                  Action item
                </Button>
              </div>
              <Button className="mt-3" onClick={() => complete.mutate()} loading={complete.isPending}>
                Save and close meeting
              </Button>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          {scheduled && !organiser && m.my_response && (
            <Card className="p-4">
              <CardHeader title="Are you going?" />
              <div className="grid grid-cols-2 gap-2">
                <Button variant={m.my_response === "ACCEPTED" ? "primary" : "outline"} onClick={() => respond.mutate(true)}>
                  Going
                </Button>
                <Button variant={m.my_response === "DECLINED" ? "danger" : "outline"} onClick={() => respond.mutate(false)}>
                  Can't make it
                </Button>
              </div>
            </Card>
          )}
          <Card className="p-4">
            <CardHeader title={`People (${m.attendees.length})`} />
            {m.attendees.map((a) => (
              <label key={a.user} className="flex items-center gap-2 py-1.5 text-sm">
                {organiser && scheduled && a.user !== m.organizer && (
                  <input type="checkbox" checked={presentIds.includes(a.user)} onChange={() => setPresent(presentIds.includes(a.user) ? presentIds.filter((x) => x !== a.user) : [...presentIds, a.user])} aria-label={`${a.name} attended`} />
                )}
                <span className="flex-1">{a.name}</span>
                <Badge tone={a.response === "ACCEPTED" ? "brand" : a.response === "DECLINED" ? "danger" : "neutral"}>
                  {m.status === "DONE" && a.attended !== null ? (a.attended ? "Attended" : "Missed") : a.response_label}
                </Badge>
              </label>
            ))}
            {organiser && scheduled && <p className="mt-1 text-xs text-muted">Tick who attended before closing the meeting.</p>}
          </Card>
          {organiser && scheduled && (
            <Card className="space-y-2 p-4">
              <Button block variant="ghost" className="text-danger" icon={<CalendarClock className="size-4" />} onClick={() => cancel.mutate(false)}>
                Cancel this meeting
              </Button>
              {m.repeats_daily && (
                <Button block variant="ghost" className="text-danger" onClick={() => cancel.mutate(true)}>
                  Stop the daily series
                </Button>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
