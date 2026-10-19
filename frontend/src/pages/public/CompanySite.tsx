/** The public company website: About (live numbers, leadership, cities), Careers (open roles and
 * an application form for each) and Contact. No sign-in needed. */

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Briefcase, Building2, CarTaxiFront, Mail, MapPin, Send, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, NavLink, useParams } from "react-router";
import { toast } from "sonner";

import { Logo } from "@/components/Logo";
import { Badge, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

interface Job {
  id: number;
  title: string;
  department: string;
  city: string;
  kind: string;
  summary: string;
  posted_at: string;
  description?: string;
}
interface About {
  numbers: { cities: number; states: number; drivers: number; riders: number; trips: number; employees: number };
  cities: string[];
  leaders: { name: string; title: string }[];
  departments: string[];
  jobs: Job[];
}

const useAbout = () => useQuery({ queryKey: ["public", "company"], queryFn: () => api.get<About>("public/company/") });
const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function Shell({ children }: { children: ReactNode }) {
  const tab = ({ isActive }: { isActive: boolean }) => `rounded-full px-3 py-1.5 text-sm font-semibold transition ${isActive ? "bg-white/15 text-white" : "text-white/70 hover:text-white"}`;
  return (
    <div className="min-h-full bg-canvas">
      <header className="bg-[image:var(--gradient-hero)] text-white">
        <nav className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-5 py-4">
          <Link to="/" aria-label="Ride Pulse home" className="[&_span]:!text-white">
            <Logo />
          </Link>
          <div className="flex items-center gap-1">
            <NavLink to="/company" end className={tab}>About</NavLink>
            <NavLink to="/careers" className={tab}>Careers</NavLink>
            <NavLink to="/contact" className={tab}>Contact</NavLink>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-10">{children}</main>
      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-8 text-sm text-muted">
        <span>© 2026 Ride Pulse Mobility Pvt. Ltd. · Chennai</span>
        <span className="flex gap-4">
          <Link to="/" className="hover:text-fg">Ride with us</Link>
          <Link to="/status" className="hover:text-fg">Service status</Link>
          <Link to="/grievance-officer" className="hover:text-fg">Grievance officer</Link>
        </span>
      </footer>
    </div>
  );
}

export function CompanyAbout() {
  const q = useAbout();
  const d = q.data;
  const stats: [string, number | undefined, typeof Users][] = [
    ["cities", d?.numbers.cities, MapPin],
    ["drivers earning with us", d?.numbers.drivers, CarTaxiFront],
    ["riders", d?.numbers.riders, Users],
    ["people on the team", d?.numbers.employees, Building2],
  ];
  return (
    <Shell>
      <section className="grid gap-8 md:grid-cols-[1.2fr_1fr] md:items-center">
        <div>
          <Badge tone="brand">About Ride Pulse</Badge>
          <h1 className="mt-3 text-4xl leading-tight font-bold tracking-tight md:text-5xl">Fair rides for riders. Fair pay for drivers.</h1>
          <p className="mt-4 text-lg text-muted">
            We started in Chennai with one promise: a fare you can trust, a safe trip, and a driver who earns well. Today we run cars, autos, bikes, parcels, rentals and
            intercity trips across {d?.numbers.states ?? 4} South Indian states, in the languages people actually speak.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link to="/careers"><Button variant="brand" icon={<Briefcase className="size-4" />}>Join us ({d?.jobs.length ?? 0} open roles)</Button></Link>
            <Link to="/contact"><Button variant="outline" icon={<Mail className="size-4" />}>Talk to us</Button></Link>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {stats.map(([label, n, Icon]) => (
            <Card key={label} className="p-5">
              <Icon className="size-5 text-brand" />
              <div className="mt-3 font-[family-name:var(--font-display)] text-3xl font-bold tabular-nums">{n?.toLocaleString("en-IN") ?? "—"}</div>
              <div className="text-sm text-muted">{label}</div>
            </Card>
          ))}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="text-2xl font-bold">What we believe</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {[
            ["Drivers first", "Low commission, weekly payouts, loans at fair rates, and a say in how we run."],
            ["Safety, always", "Ride checks, SOS answered in minutes, women-safety sharing, and trained drivers."],
            ["Local by design", "Tamil, Hindi, Malayalam, Kannada and Telugu, metro first and last mile, and festival-aware pricing."],
          ].map(([t, b]) => (
            <Card key={t} className="p-5">
              <div className="font-semibold">{t}</div>
              <p className="mt-1 text-sm text-muted">{b}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="text-2xl font-bold">Leadership</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {d?.leaders.map((l) => (
            <Card key={l.name} className="flex items-center gap-3 p-4">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-[image:var(--gradient-brand)] font-bold text-white">
                {l.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}
              </div>
              <div>
                <div className="font-semibold">{l.name}</div>
                <div className="text-sm text-muted">{l.title}</div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="text-2xl font-bold">Where we are</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {d?.cities.map((c) => (
            <span key={c} className="rounded-full bg-surface px-3 py-1 text-sm shadow-[var(--shadow-card)]">{c}</span>
          ))}
        </div>
      </section>
    </Shell>
  );
}

export function Careers() {
  const q = useAbout();
  const [dept, setDept] = useState("");
  const jobs = (q.data?.jobs ?? []).filter((j) => !dept || j.department === dept);
  const depts = [...new Set((q.data?.jobs ?? []).map((j) => j.department))];
  return (
    <Shell>
      <h1 className="text-4xl font-bold tracking-tight">Careers</h1>
      <p className="mt-2 max-w-2xl text-lg text-muted">Help millions of people get where they're going. Health cover for your family, a learning budget, and free rides to work.</p>
      <div className="mt-6 flex flex-wrap gap-2">
        {["", ...depts].map((d) => (
          <button key={d || "all"} onClick={() => setDept(d)} className={`rounded-full px-3 py-1.5 text-sm font-semibold ${dept === d ? "bg-ink text-ink-fg" : "bg-surface text-muted shadow-[var(--shadow-card)]"}`}>
            {d || "All teams"}
          </button>
        ))}
      </div>
      <div className="mt-6 grid gap-3">
        {q.data && !jobs.length && <p className="text-muted">No open roles right now. Check back soon.</p>}
        {jobs.map((j) => (
          <Link key={j.id} to={`/careers/${j.id}`} className="card flex flex-wrap items-center justify-between gap-3 p-5">
            <div>
              <div className="text-lg font-semibold">{j.title}</div>
              <div className="text-sm text-muted">{j.department} · {j.city} · {j.kind}</div>
              <div className="mt-1 text-sm">{j.summary}</div>
            </div>
            <ArrowRight className="size-5 text-brand" />
          </Link>
        ))}
      </div>
    </Shell>
  );
}

export function CareerDetail() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["public", "job", id], queryFn: () => api.get<Job>(`public/company/jobs/${id}/`) });
  const [form, setForm] = useState({ name: "", email: "", phone: "", profile_url: "", note: "" });
  const [done, setDone] = useState(false);
  const apply = useMutation({ mutationFn: () => api.post(`public/company/jobs/${id}/`, form), onSuccess: () => setDone(true), onError: fail });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const j = q.data;
  return (
    <Shell>
      <Link to="/careers" className="inline-flex items-center gap-1 text-sm font-semibold text-brand"><ArrowLeft className="size-4" /> All roles</Link>
      {q.error && <p className="mt-6 text-muted">This role is no longer open.</p>}
      {j && (
        <div className="mt-4 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{j.title}</h1>
            <div className="mt-1 text-muted">{j.department} · {j.city} · {j.kind}</div>
            <p className="mt-6 whitespace-pre-line leading-relaxed">{j.description}</p>
          </div>
          <Card className="h-fit p-5">
            {done ? (
              <div className="py-6 text-center">
                <div className="text-4xl">🎉</div>
                <div className="mt-2 text-lg font-semibold">Thank you for applying!</div>
                <p className="mt-1 text-sm text-muted">Our people team reads every application and will get back to you within a week.</p>
              </div>
            ) : (
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); apply.mutate(); }}>
                <div className="text-lg font-semibold">Apply for this role</div>
                <Field label="Full name"><Input required value={form.name} onChange={set("name")} autoComplete="name" /></Field>
                <Field label="Email"><Input required type="email" value={form.email} onChange={set("email")} autoComplete="email" /></Field>
                <Field label="Mobile number"><Input required value={form.phone} onChange={set("phone")} autoComplete="tel" inputMode="tel" /></Field>
                <Field label="LinkedIn or portfolio (optional)"><Input type="url" value={form.profile_url} onChange={set("profile_url")} placeholder="https://" /></Field>
                <Field label="Why you? (optional)"><Textarea value={form.note} onChange={set("note")} maxLength={2000} /></Field>
                <Button type="submit" variant="brand" block loading={apply.isPending} icon={<Send className="size-4" />}>Send application</Button>
              </form>
            )}
          </Card>
        </div>
      )}
    </Shell>
  );
}

export function Contact() {
  const [form, setForm] = useState({ name: "", email: "", topic: "GENERAL", message: "" });
  const [done, setDone] = useState(false);
  const send = useMutation({ mutationFn: () => api.post("public/company/contact/", form), onSuccess: () => setDone(true), onError: fail });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Shell>
      <div className="grid gap-8 md:grid-cols-2">
        <div>
          <h1 className="text-4xl font-bold tracking-tight">Talk to us</h1>
          <p className="mt-3 text-lg text-muted">Partnerships, business travel for your company, press, or anything else. We reply within two working days.</p>
          <div className="mt-6 space-y-2 text-sm">
            <div><span className="font-semibold">Head office:</span> Ride Pulse Mobility Pvt. Ltd., Anna Salai, Chennai 600002</div>
            <div><span className="font-semibold">Riders and drivers:</span> help is in the app, under Support, 24×7.</div>
          </div>
        </div>
        <Card className="p-5">
          {done ? (
            <div className="py-8 text-center">
              <div className="text-4xl">✉️</div>
              <div className="mt-2 text-lg font-semibold">Thanks, we've got your message.</div>
            </div>
          ) : (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
              <Field label="Name"><Input required value={form.name} onChange={set("name")} autoComplete="name" /></Field>
              <Field label="Email"><Input required type="email" value={form.email} onChange={set("email")} autoComplete="email" /></Field>
              <Field label="About">
                <Select value={form.topic} onChange={set("topic")}>
                  <option value="GENERAL">General</option>
                  <option value="PARTNERSHIP">Partnerships</option>
                  <option value="CORPORATE">Business travel</option>
                  <option value="PRESS">Press</option>
                </Select>
              </Field>
              <Field label="Message"><Textarea required value={form.message} onChange={set("message")} maxLength={3000} /></Field>
              <Button type="submit" variant="brand" block loading={send.isPending} icon={<Send className="size-4" />}>Send</Button>
            </form>
          )}
        </Card>
      </div>
    </Shell>
  );
}
