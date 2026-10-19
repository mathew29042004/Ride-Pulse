/** Ops → Company: the employee intranet. Messages from the commander (who can post one here),
 * staff announcements, birthdays and anniversaries this week, new joiners, departments, holidays,
 * the people directory, open roles to refer friends to, and (for HR) applications to review. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building, CalendarDays, Crown, Gift, Megaphone, Search, Sparkles, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, PageHeader, Select, Table, Td, Textarea, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";

interface Home {
  me: { name: string; first_name: string; title: string };
  leader_messages: { id: number; title: string; body: string; author: string; posted_at: string }[];
  announcements: { id: number; title: string; body: string; created_at: string }[];
  celebrations: { name: string; title: string; what: string; date: string; today: boolean }[];
  new_joiners: { name: string; title: string; joined_on: string }[];
  departments: { key: string; name: string; people: number; head: string }[];
  holidays: { date: string; name: string; state: string }[];
  jobs: { id: number; title: string; department: string; city: string; kind: string; summary: string }[];
  headcount: number;
}
interface Person {
  id: number;
  name: string;
  title: string;
  department: string;
  city: string;
  email: string;
  phone: string;
  employee_id: string;
  manager: string;
}
interface Application {
  id: number;
  job: string;
  name: string;
  email: string;
  phone: string;
  profile_url: string;
  note: string;
  referred_by: string;
  status: string;
  status_label: string;
  applied_at: string;
}

const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

export default function OpsCompany() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["company"], queryFn: () => api.get<Home>("company/") });
  const d = q.data;
  const [writing, setWriting] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const post = useMutation({
    mutationFn: () => api.post("company/message/", { title, body }),
    onSuccess: () => {
      toast.success("Posted to the whole company.");
      setWriting(false);
      setTitle("");
      setBody("");
      qc.invalidateQueries({ queryKey: ["company"] });
    },
    onError: fail,
  });
  const [referFor, setReferFor] = useState<Home["jobs"][number] | null>(null);
  return (
    <>
      <PageHeader
        title={d ? `Hello, ${d.me.first_name} 👋` : "Company"}
        subtitle={d ? `${d.headcount} people building Ride Pulse together.` : "Ride Pulse, together."}
        actions={
          <>
            {can("command") && <Button variant="outline" icon={<Crown className="size-4" />} onClick={() => setWriting(true)}>Message the company</Button>}
            <Link to="/company" target="_blank"><Button variant="outline" icon={<Building className="size-4" />}>Public website</Button></Link>
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-4">
          {d?.leader_messages.map((m) => (
            <Card key={m.id} className="overflow-hidden">
              <div className="bg-[image:var(--gradient-brand)] px-5 py-3 text-sm font-semibold text-white"><Crown className="mr-1 inline size-4" /> From {m.author}</div>
              <div className="p-5">
                <div className="text-lg font-bold">{m.title}</div>
                <p className="mt-2 whitespace-pre-line text-sm leading-relaxed">{m.body}</p>
                <div className="mt-2 text-xs text-muted">{dateTime(m.posted_at)}</div>
              </div>
            </Card>
          ))}
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Megaphone className="size-4 text-brand" /> Announcements</span>} />
            {d && !d.announcements.length && <EmptyState title="No announcements yet" />}
            <div className="divide-y divide-line">
              {d?.announcements.map((a) => (
                <div key={a.id} className="px-5 py-3 text-sm">
                  <div className="font-semibold">{a.title}</div>
                  <p className="mt-0.5 text-muted">{a.body}</p>
                  <div className="mt-0.5 text-xs text-muted">{dateTime(a.created_at)}</div>
                </div>
              ))}
            </div>
          </Card>
          <Directory />
          {can("people.manage") && <Applications />}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Gift className="size-4 text-pink-500" /> This week</span>} subtitle="Birthdays and work anniversaries" />
            {d && !d.celebrations.length && <EmptyState title="Nothing this week" />}
            <div className="divide-y divide-line">
              {d?.celebrations.map((c) => (
                <div key={c.name + c.what} className={`flex items-center justify-between gap-2 px-5 py-2.5 text-sm ${c.today ? "bg-pink-500/5" : ""}`}>
                  <div>
                    <div className="font-semibold">{c.what === "Birthday" ? "🎂" : "🎉"} {c.name}</div>
                    <div className="text-xs text-muted">{c.what} · {c.title}</div>
                  </div>
                  <Badge tone={c.today ? "brand" : "neutral"}>{c.today ? "Today" : day(c.date)}</Badge>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-amber-500" /> Welcome aboard</span>} subtitle="Joined in the last few weeks" />
            {d && !d.new_joiners.length && <EmptyState title="No new joiners lately" />}
            <div className="divide-y divide-line">
              {d?.new_joiners.map((p) => (
                <div key={p.name} className="px-5 py-2 text-sm"><span className="font-semibold">{p.name}</span> <span className="text-muted">· {p.title}</span></div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><CalendarDays className="size-4 text-sky-500" /> Holidays</span>} />
            <div className="divide-y divide-line">
              {d?.holidays.map((h) => (
                <div key={h.date + h.name} className="flex items-center justify-between px-5 py-2 text-sm">
                  <span>{h.name} <span className="text-xs text-muted">· {h.state}</span></span>
                  <span className="text-muted">{day(h.date)}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><UserPlus className="size-4 text-brand" /> Open roles: refer a friend</span>} />
            <div className="divide-y divide-line">
              {d?.jobs.map((j) => (
                <div key={j.id} className="flex items-center justify-between gap-2 px-5 py-2.5 text-sm">
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{j.title}</div>
                    <div className="text-xs text-muted">{j.department} · {j.city}</div>
                  </div>
                  <Button size="sm" variant="secondary" onClick={() => setReferFor(j)}>Refer</Button>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Users className="size-4" /> Departments</span>} />
            <div className="divide-y divide-line">
              {d?.departments.map((x) => (
                <div key={x.key} className="flex items-center justify-between px-5 py-2 text-sm">
                  <div>
                    <div className="font-semibold">{x.name}</div>
                    {x.head && <div className="text-xs text-muted">Led by {x.head}</div>}
                  </div>
                  <Badge>{x.people} people</Badge>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Modal open={writing} onClose={() => setWriting(false)} title="Message the whole company" footer={<Button loading={post.isPending} disabled={title.trim().length < 3 || body.trim().length < 20} onClick={() => post.mutate()}>Post to everyone</Button>}>
        <div className="space-y-3">
          <Field label="Title"><Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} /></Field>
          <Field label="Message" hint="Everyone on the team is notified."><Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-40" maxLength={6000} /></Field>
        </div>
      </Modal>
      {referFor && <Refer job={referFor} onClose={() => setReferFor(null)} />}
    </>
  );
}

function Directory() {
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const people = useQuery({
    queryKey: ["company", "directory", q, dept],
    queryFn: () => api.get<{ people: Person[] }>(`company/directory/?q=${encodeURIComponent(q)}&department=${dept}`),
  });
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Search className="size-4" /> People directory</span>} subtitle="Find anyone by name, title, email or employee ID." />
      <div className="flex flex-wrap gap-2 px-5 pt-4">
        <Input className="flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search people" aria-label="Search people" />
        <Select className="!w-48" value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Department">
          <option value="">All departments</option>
          {["LEADERSHIP", "OPERATIONS", "RIDES", "SUPPORT", "MAINTENANCE", "INTERCITY", "PARCELS", "FINANCE", "PEOPLE", "SAFETY", "LEGAL", "TECH"].map((k) => (
            <option key={k} value={k}>{k.charAt(0) + k.slice(1).toLowerCase()}</option>
          ))}
        </Select>
      </div>
      <div className="mt-3 max-h-[28rem] overflow-y-auto">
        <Table>
          <thead>
            <tr><Th>Name</Th><Th>Department</Th><Th>Where</Th><Th>Contact</Th></tr>
          </thead>
          <tbody>
            {people.data?.people.map((p) => (
              <tr key={p.id}>
                <Td>
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-xs text-muted">{p.title}{p.manager ? ` · reports to ${p.manager}` : ""}</div>
                </Td>
                <Td>{p.department}</Td>
                <Td>{p.city}</Td>
                <Td className="text-xs">
                  <a className="text-brand hover:underline" href={`mailto:${p.email}`}>{p.email}</a>
                  {p.phone && <div className="text-muted">{p.phone}</div>}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </Card>
  );
}

function Refer({ job, onClose }: { job: Home["jobs"][number]; onClose: () => void }) {
  const [form, setForm] = useState({ name: "", email: "", phone: "", note: "" });
  const refer = useMutation({
    mutationFn: () => api.post("company/refer/", { ...form, job: job.id }),
    onSuccess: () => {
      toast.success("Referred. HR will be in touch, and we'll tell you how it goes.");
      onClose();
    },
    onError: fail,
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title={`Refer someone: ${job.title}`} footer={<Button loading={refer.isPending} disabled={!form.name || !form.email || !form.phone} onClick={() => refer.mutate()}>Send referral</Button>}>
      <div className="space-y-3">
        <Field label="Their name"><Input value={form.name} onChange={set("name")} /></Field>
        <Field label="Their email"><Input type="email" value={form.email} onChange={set("email")} /></Field>
        <Field label="Their mobile"><Input value={form.phone} onChange={set("phone")} /></Field>
        <Field label="Why they'd be great (optional)"><Textarea value={form.note} onChange={set("note")} /></Field>
      </div>
    </Modal>
  );
}

function Applications() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["company", "applications"], queryFn: () => api.get<{ applications: Application[] }>("company/applications/") });
  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.post(`company/applications/${id}/status/`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["company", "applications"] }),
    onError: fail,
  });
  return (
    <Card>
      <CardHeader title="Applications" subtitle="From the careers page and staff referrals." />
      {q.data && !q.data.applications.length && <EmptyState title="No applications yet" />}
      <div className="divide-y divide-line">
        {q.data?.applications.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
            <div className="min-w-0">
              <div className="font-semibold">{a.name} <span className="font-normal text-muted">→ {a.job}</span></div>
              <div className="text-xs text-muted">
                {a.email} · {a.phone}{a.referred_by ? ` · referred by ${a.referred_by}` : ""} · {dateTime(a.applied_at)}
              </div>
              {a.note && <div className="mt-0.5 text-xs">{a.note}</div>}
            </div>
            <Select className="!w-40 !py-1.5" value={a.status} onChange={(e) => move.mutate({ id: a.id, status: e.target.value })} aria-label="Status">
              <option value="NEW">New</option>
              <option value="SHORTLISTED">Shortlisted</option>
              <option value="INTERVIEW">Interview</option>
              <option value="HIRED">Hired</option>
              <option value="REJECTED">Not this time</option>
            </Select>
          </div>
        ))}
      </div>
    </Card>
  );
}
