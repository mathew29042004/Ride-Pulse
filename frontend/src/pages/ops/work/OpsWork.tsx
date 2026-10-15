/**
 * Manager workspace: give work to your team, run daily stand-ups, chase status, and see who's
 * on track. Everyone sees their own tasks; managers see their whole part of the org chart.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlarmClock, CalendarClock, CheckCircle2, ClipboardList, LifeBuoy, MessageCircleQuestion, Plus, Repeat, Users } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, PageHeader, Segmented, Select, Stat, Table, Td, Textarea, Th, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Paginated } from "@/lib/types";

import { type Dashboard, localInput, type Meeting, type Person, PRIORITY_TONE, toIso, type WorkTask } from "./api";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
type Tab = "dashboard" | "tasks" | "meetings";

export default function OpsWork() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "dashboard";
  const people = useQuery({ queryKey: ["work", "people"], queryFn: () => api.get<Person[]>("work/people/") });
  const isManager = (people.data ?? []).length > 0;
  const [newTask, setNewTask] = useState(false);
  const [newMeeting, setNewMeeting] = useState(false);

  return (
    <>
      <PageHeader
        title="Work"
        subtitle={isManager ? "Give your team work, run stand-ups, and see who's on track." : "Your tasks and meetings."}
        actions={
          isManager && (
            <div className="flex gap-2">
              <Button variant="outline" icon={<CalendarClock className="size-4" />} onClick={() => setNewMeeting(true)}>
                Meeting
              </Button>
              <Button icon={<Plus className="size-4" />} onClick={() => setNewTask(true)}>
                Task
              </Button>
            </div>
          )
        }
      />
      <Segmented
        value={tab}
        onChange={(v) => setParams({ tab: v })}
        options={[
          { value: "dashboard", label: isManager ? "Team dashboard" : "Overview" },
          { value: "tasks", label: "Tasks" },
          { value: "meetings", label: "Meetings" },
        ]}
      />
      <div className="mt-4">
        {tab === "dashboard" && (isManager ? <TeamDashboard /> : <MyOverview />)}
        {tab === "tasks" && <TaskList isManager={isManager} />}
        {tab === "meetings" && <MeetingList />}
      </div>
      <NewTaskModal open={newTask} onClose={() => setNewTask(false)} people={people.data ?? []} />
      <NewMeetingModal open={newMeeting} onClose={() => setNewMeeting(false)} people={people.data ?? []} />
    </>
  );
}

// --- Dashboard -------------------------------------------------------------------------------

function TeamDashboard() {
  const [days, setDays] = useState("7");
  const [scope, setScope] = useState<"direct" | "all">("direct");
  const board = useQuery({ queryKey: ["work", "dashboard", days], queryFn: () => api.get<Dashboard>(`work/dashboard/?days=${days}`), refetchInterval: 20_000 });
  const d = board.data;
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const rows = (d?.people ?? []).filter((r) => (scope === "all" || r.direct_report) && (!onlyFlagged || r.needs_guidance));
  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="People in your team" value={d?.totals.people ?? "—"} icon={<Users className="size-4" />} tone="brand" />
        <Stat label="Open tasks" value={d?.totals.open_tasks ?? "—"} icon={<ClipboardList className="size-4" />} tone="info" />
        <Stat label="Overdue" value={d?.totals.overdue_tasks ?? "—"} icon={<AlarmClock className="size-4" />} tone={d?.totals.overdue_tasks ? "danger" : "neutral"} />
        <Stat label={`Done (${days} days)`} value={d?.totals.done_tasks ?? "—"} sub={`On time: ${pct(d?.totals.on_time_rate ?? null)}`} icon={<CheckCircle2 className="size-4" />} tone="brand" />
        <Stat label="Need guidance" value={d?.totals.needs_guidance ?? "—"} sub={d?.totals.avg_response_minutes != null ? `Avg ticket reply ${d.totals.avg_response_minutes} min` : ""} icon={<LifeBuoy className="size-4" />} tone={d?.totals.needs_guidance ? "warning" : "neutral"} />
        <Stat label={`Output (${days} days)`} value={d ? d.totals.tickets_resolved + d.totals.documents_reviewed : "—"} sub={d ? `${d.totals.tickets_resolved} tickets · ${d.totals.documents_reviewed} documents` : ""} icon={<CheckCircle2 className="size-4" />} />
      </div>

      {d && d.departments.length > 1 && (
        <Card className="mt-4 p-4">
          <CardHeader title="By department" />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {d.departments.map((dept) => (
              <div key={dept.department} className="rounded-xl bg-surface-2 px-3 py-2 text-sm">
                <div className="font-semibold">{dept.department}</div>
                <div className="text-xs text-muted">
                  {dept.people} people · {dept.open} open · <span className={clsx(dept.overdue && "font-semibold text-danger")}>{dept.overdue} overdue</span> · {dept.done} done
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="mt-4 overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 p-4">
          <div className="flex-1">
            <div className="font-semibold">Scorecards</div>
            <div className="text-xs text-muted">Real output from their work: tickets resolved, driver documents reviewed, tasks on time, meetings attended.</div>
          </div>
          <label className="flex items-center gap-2 text-xs text-muted">
            <Toggle checked={onlyFlagged} onChange={setOnlyFlagged} label="Only people who need guidance" /> Needs guidance
          </label>
          <Segmented value={scope} onChange={setScope} options={[{ value: "direct", label: "Direct reports" }, { value: "all", label: "Everyone below me" }]} />
          <Select value={days} onChange={(e) => setDays(e.target.value)} className="!w-auto">
            <option value="7">7 days</option>
            <option value="30">30 days</option>
          </Select>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>Person</Th>
                <Th className="text-right">Open</Th>
                <Th className="text-right">Overdue</Th>
                <Th className="text-right">Done</Th>
                <Th className="text-right">On time</Th>
                <Th className="text-right">Tickets</Th>
                <Th className="text-right">Reply</Th>
                <Th className="text-right">SLA met</Th>
                <Th className="text-right">Documents</Th>
                <Th className="text-right">Review time</Th>
                <Th className="text-right">Meetings</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.user_id} className="border-t border-line">
                  <Td>
                    <div className="flex items-center gap-1.5 font-semibold">
                      {r.name} {r.needs_guidance && <Badge tone="warning">Needs guidance</Badge>}
                    </div>
                    <div className="text-xs text-muted">
                      {r.title}
                      {r.city && ` · ${r.city}`}
                      {!r.direct_report && r.manager && ` · reports to ${r.manager}`}
                    </div>
                  </Td>
                  <Td className="text-right">{r.open_tasks}</Td>
                  <Td className={clsx("text-right", r.overdue_tasks && "font-semibold text-danger")}>{r.overdue_tasks}</Td>
                  <Td className="text-right">{r.done_tasks}</Td>
                  <Td className="text-right">{pct(r.on_time_rate)}</Td>
                  <Td className="text-right">{r.tickets_resolved || "—"}</Td>
                  <Td className={clsx("text-right", (r.avg_response_minutes ?? 0) > 120 && "font-semibold text-danger")}>{r.avg_response_minutes != null ? `${r.avg_response_minutes}m` : "—"}</Td>
                  <Td className="text-right">{pct(r.sla_met_rate)}</Td>
                  <Td className="text-right">{r.documents_reviewed || "—"}</Td>
                  <Td className="text-right">{r.avg_review_hours != null ? `${r.avg_review_hours}h` : "—"}</Td>
                  <Td className="text-right">{pct(r.meeting_attendance)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {rows.length === 0 && <p className="p-6 text-center text-sm text-muted">Nobody here yet.</p>}
        </div>
      </Card>
    </>
  );
}

function MyOverview() {
  const open = useQuery({ queryKey: ["work", "tasks", "mine", "open"], queryFn: () => api.get<Paginated<WorkTask>>("work/tasks/?scope=mine&state=open") });
  const meetings = useQuery({ queryKey: ["work", "meetings", "upcoming"], queryFn: () => api.get<Paginated<Meeting>>("work/meetings/?when=upcoming") });
  const tasks = open.data?.results ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4">
        <CardHeader title="My open tasks" subtitle={`${tasks.filter((t) => t.is_overdue).length} overdue`} />
        <div className="space-y-2">{tasks.length ? tasks.map((t) => <TaskRow key={t.id} task={t} />) : <p className="text-sm text-muted">Nothing on your plate.</p>}</div>
      </Card>
      <Card className="p-4">
        <CardHeader title="Upcoming meetings" />
        <div className="space-y-2">{(meetings.data?.results ?? []).map((m) => <MeetingRow key={m.id} meeting={m} />)}</div>
      </Card>
    </div>
  );
}

// --- Tasks -----------------------------------------------------------------------------------

export function TaskRow({ task }: { task: WorkTask }) {
  return (
    <Link to={`/ops/work/tasks/${task.id}`} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5 hover:bg-surface-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold">{task.title}</span>
          {task.awaiting_update && <MessageCircleQuestion className="size-4 shrink-0 text-amber-600" aria-label="Status requested" />}
        </div>
        <div className="truncate text-xs text-muted">
          {task.mine ? `From ${task.assigned_by_name}` : task.assignee_name} · due {dateTime(task.due_at)}
          {task.target ? ` · ${task.progress}/${task.target}` : ""}
        </div>
        {task.target ? (
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(100, (100 * task.progress) / task.target)}%` }} />
          </div>
        ) : null}
      </div>
      <Badge tone={PRIORITY_TONE[task.priority]}>{task.priority_label}</Badge>
      <Badge tone={task.is_overdue ? "danger" : task.status === "DONE" ? "brand" : "neutral"}>{task.is_overdue ? "Overdue" : task.status_label}</Badge>
    </Link>
  );
}

function TaskList({ isManager }: { isManager: boolean }) {
  // People load after the first render, so the default follows isManager until a choice is made.
  const [picked, setScope] = useState<string | null>(null);
  const scope = picked ?? (isManager ? "team" : "mine");
  const [state, setState] = useState("open");
  const tasks = useQuery({
    queryKey: ["work", "tasks", scope, state],
    queryFn: () => api.get<Paginated<WorkTask>>(`work/tasks/?scope=${scope}&state=${state}&page_size=100`),
    refetchInterval: 15_000,
  });
  const list = tasks.data?.results ?? [];
  return (
    <>
      <div className="flex flex-wrap gap-3">
        {isManager && (
          <Segmented
            value={scope}
            onChange={setScope}
            options={[
              { value: "team", label: "My team" },
              { value: "given", label: "Given by me" },
              { value: "mine", label: "Mine" },
            ]}
          />
        )}
        <Segmented
          value={state}
          onChange={setState}
          options={[
            { value: "open", label: "Open" },
            { value: "overdue", label: "Overdue" },
            { value: "done", label: "Done" },
            { value: "all", label: "All" },
          ]}
        />
      </div>
      <div className="mt-4 space-y-2">
        {list.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
        {!tasks.isLoading && list.length === 0 && <EmptyState icon={<ClipboardList className="size-6" />} title="No tasks here" />}
      </div>
    </>
  );
}

function PeoplePicker({ people, selected, onChange }: { people: Person[]; selected: number[]; onChange: (ids: number[]) => void }) {
  const [search, setSearch] = useState("");
  const [allLevels, setAllLevels] = useState(false);
  const shown = people.filter((p) => (allLevels || p.direct) && `${p.name} ${p.title} ${p.city}`.toLowerCase().includes(search.toLowerCase())).slice(0, 60);
  const toggle = (id: number) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div>
      <div className="flex items-center gap-2">
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search people" className="!py-2" />
        <label className="flex shrink-0 items-center gap-2 text-xs text-muted">
          <Toggle checked={allLevels} onChange={setAllLevels} label="Everyone below me" /> All levels
        </label>
      </div>
      <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
        {shown.map((p) => (
          <label key={p.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface-2">
            <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} />
            <span className="flex-1">
              {p.name} <span className="text-xs text-muted">· {p.title}{p.city && `, ${p.city}`}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

function NewTaskModal({ open, onClose, people }: { open: boolean; onClose: () => void; people: Person[] }) {
  const qc = useQueryClient();
  const blank = { title: "", description: "", priority: "NORMAL", due: localInput(8), target: "", wholeTeam: false, ids: [] as number[] };
  const [f, setF] = useState(blank);
  const create = useMutation({
    mutationFn: () =>
      api.post<WorkTask[]>("work/tasks/", {
        title: f.title,
        description: f.description,
        priority: f.priority,
        due_at: toIso(f.due),
        target: f.target ? Number(f.target) : null,
        whole_team: f.wholeTeam,
        assignee_ids: f.ids,
      }),
    onSuccess: (tasks) => {
      toast.success(`Task given to ${tasks.length} ${tasks.length === 1 ? "person" : "people"}`);
      qc.invalidateQueries({ queryKey: ["work"] });
      setF(blank);
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New task"
      footer={
        <Button block loading={create.isPending} disabled={f.title.trim().length < 3 || (!f.wholeTeam && !f.ids.length)} onClick={() => create.mutate()}>
          Assign
        </Button>
      }
    >
      <Field label="What needs doing?">
        <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Verify 20 pending drivers today" />
      </Field>
      <Field label="Details" className="mt-3">
        <Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} rows={2} placeholder="Guidance, links, what good looks like" />
      </Field>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Field label="Priority">
          <Select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
            <option value="LOW">Low</option>
            <option value="NORMAL">Normal</option>
            <option value="HIGH">High</option>
            <option value="URGENT">Urgent</option>
          </Select>
        </Field>
        <Field label="Deadline" className="col-span-2">
          <Input type="datetime-local" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
        </Field>
      </div>
      <Field label="Target (optional)" hint="A number to count towards, like 20 drivers" className="mt-3">
        <Input type="number" min={1} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} />
      </Field>
      <div className="mt-4 flex items-center justify-between">
        <span className="label !mb-0">Who</span>
        <label className="flex items-center gap-2 text-sm">
          <Toggle checked={f.wholeTeam} onChange={(v) => setF({ ...f, wholeTeam: v })} label="All my direct reports" /> All my direct reports
        </label>
      </div>
      {!f.wholeTeam && <PeoplePicker people={people} selected={f.ids} onChange={(ids) => setF({ ...f, ids })} />}
    </Modal>
  );
}

// --- Meetings --------------------------------------------------------------------------------

export function MeetingRow({ meeting }: { meeting: Meeting }) {
  const going = meeting.attendees.filter((a) => a.response === "ACCEPTED").length;
  return (
    <Link to={`/ops/work/meetings/${meeting.id}`} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5 hover:bg-surface-2">
      <CalendarClock className="size-5 shrink-0 text-muted" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate font-semibold">
          {meeting.title} {meeting.repeats_daily && <Repeat className="size-3.5 text-muted" aria-label="Daily" />}
        </div>
        <div className="truncate text-xs text-muted">
          {dateTime(meeting.starts_at)} · {meeting.duration_minutes} min · {meeting.organizer_name} · {going}/{meeting.attendees.length} going
        </div>
      </div>
      {meeting.my_response === "INVITED" ? <Badge tone="warning">Reply</Badge> : <Badge tone={meeting.status === "DONE" ? "brand" : "neutral"}>{meeting.status_label}</Badge>}
    </Link>
  );
}

function MeetingList() {
  const [when, setWhen] = useState("upcoming");
  const meetings = useQuery({ queryKey: ["work", "meetings", when], queryFn: () => api.get<Paginated<Meeting>>(`work/meetings/?when=${when}`), refetchInterval: 20_000 });
  const list = meetings.data?.results ?? [];
  return (
    <>
      <Segmented value={when} onChange={setWhen} options={[{ value: "upcoming", label: "Upcoming" }, { value: "past", label: "Past" }]} />
      <div className="mt-4 space-y-2">
        {list.map((m) => (
          <MeetingRow key={m.id} meeting={m} />
        ))}
        {!meetings.isLoading && list.length === 0 && <EmptyState icon={<CalendarClock className="size-6" />} title="No meetings" />}
      </div>
    </>
  );
}

function NewMeetingModal({ open, onClose, people }: { open: boolean; onClose: () => void; people: Person[] }) {
  const qc = useQueryClient();
  const blank = { title: "Daily stand-up", agenda: "1. Yesterday\n2. Today\n3. Blockers", starts: localInput(1), duration: "15", daily: true, wholeTeam: true, ids: [] as number[] };
  const [f, setF] = useState(blank);
  const create = useMutation({
    mutationFn: () =>
      api.post<Meeting>("work/meetings/", {
        title: f.title,
        agenda: f.agenda,
        starts_at: toIso(f.starts),
        duration_minutes: Number(f.duration),
        repeats_daily: f.daily,
        whole_team: f.wholeTeam,
        attendee_ids: f.ids,
      }),
    onSuccess: () => {
      toast.success("Invites sent");
      qc.invalidateQueries({ queryKey: ["work"] });
      setF(blank);
      onClose();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Schedule a meeting"
      footer={
        <Button block loading={create.isPending} disabled={f.title.trim().length < 3 || (!f.wholeTeam && !f.ids.length)} onClick={() => create.mutate()}>
          Send invites
        </Button>
      }
    >
      <Field label="Title">
        <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
      </Field>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Field label="Starts" className="col-span-2">
          <Input type="datetime-local" value={f.starts} onChange={(e) => setF({ ...f, starts: e.target.value })} />
        </Field>
        <Field label="Minutes">
          <Select value={f.duration} onChange={(e) => setF({ ...f, duration: e.target.value })}>
            {["10", "15", "30", "45", "60"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label="Agenda" className="mt-3">
        <Textarea value={f.agenda} onChange={(e) => setF({ ...f, agenda: e.target.value })} rows={3} />
      </Field>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <Toggle checked={f.daily} onChange={(v) => setF({ ...f, daily: v })} label="Repeat every weekday" /> Repeat every weekday (daily stand-up)
      </label>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <Toggle checked={f.wholeTeam} onChange={(v) => setF({ ...f, wholeTeam: v })} label="Invite all my direct reports" /> Invite all my direct reports
      </label>
      {!f.wholeTeam && (
        <div className="mt-2">
          <PeoplePicker people={people} selected={f.ids} onChange={(ids) => setF({ ...f, ids })} />
        </div>
      )}
    </Modal>
  );
}
