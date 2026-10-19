import {
  ArrowRight,
  BadgeIndianRupee,
  Car,
  ChartNoAxesCombined,
  Gauge,
  KeyRound,
  MapPinned,
  Radio,
  ShieldAlert,
  Sparkles,
  Wallet,
  Zap,
} from "lucide-react";
import { Link } from "react-router";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";

const FEATURES = [
  { icon: MapPinned, title: "Live tracking", text: "Watch your driver approach in real time over WebSockets, from booking to drop-off." },
  { icon: BadgeIndianRupee, title: "Upfront fares", text: "See the exact price before you book. GST, surge and promo codes are explained line by line." },
  { icon: Zap, title: "Smart dispatch", text: "Nearest-driver matching, or batched assignment with the Hungarian algorithm for the whole city." },
  { icon: Gauge, title: "Dynamic surge", text: "Prices respond to demand and supply in each neighbourhood, smoothed and capped." },
  { icon: KeyRound, title: "Ride PIN", text: "Trips start only when the rider shares a 4-digit PIN with the right driver." },
  { icon: ShieldAlert, title: "SOS safety desk", text: "One tap alerts the safety team with the live location of the trip." },
  { icon: Wallet, title: "Wallet & UPI", text: "Double-entry ledger, idempotent payments, cash commission dues and weekly payouts." },
  { icon: ChartNoAxesCombined, title: "Operations console", text: "KPIs, demand heatmaps, driver verification, support tickets and a full audit trail." },
];

const STACK = [
  "Python 3.12",
  "Django 5.2 LTS",
  "Django REST Framework",
  "PostgreSQL 16",
  "Channels · WebSockets",
  "Celery · Redis",
  "JWT auth",
  "OpenAPI / Swagger",
  "React 19",
  "TypeScript",
  "Tailwind CSS",
  "Leaflet maps",
  "Docker",
  "GitHub Actions",
];

export default function Landing() {
  const { user } = useAuth();
  return (
    <div className="min-h-full bg-surface">
      <header className="relative overflow-hidden bg-[#070a10] text-white">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_20%_10%,rgb(16_185_129/0.35),transparent_45%),radial-gradient(ellipse_at_90%_80%,rgb(14_165_233/0.25),transparent_40%)]" />
        <div className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(white_1px,transparent_1px),linear-gradient(90deg,white_1px,transparent_1px)] [background-size:44px_44px]" />
        <nav className="relative mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
          <Logo light />
          <div className="flex items-center gap-2">
            {user ? (
              <Link to={homeFor(user.role)}>
                <Button variant="brand" size="sm" icon={<ArrowRight className="size-4" />}>
                  Open app
                </Button>
              </Link>
            ) : (
              <>
                <Link to="/login" className="px-3 py-2 text-sm font-medium text-white/80 hover:text-white">
                  Log in
                </Link>
                <Link to="/signup">
                  <Button variant="brand" size="sm">
                    Sign up
                  </Button>
                </Link>
              </>
            )}
          </div>
        </nav>

        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-5 pt-10 pb-24 md:grid-cols-[1.1fr_0.9fr] md:pt-16">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-emerald-300">
              <Radio className="size-3.5" /> Live in Chennai · Bengaluru · Coimbatore
            </span>
            <h1 className="mt-5 text-4xl leading-[1.05] font-bold tracking-tight md:text-6xl">
              Your city,
              <br />
              <span className="bg-gradient-to-r from-emerald-300 to-sky-300 bg-clip-text text-transparent">on the move.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg text-white/70">
              Ride Pulse is a complete ride-hailing platform: a rider app, a driver app and an operations console, running on
              one Django and PostgreSQL back end with real-time dispatch.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to={user?.role === "RIDER" ? "/ride" : "/signup"}>
                <Button variant="brand" size="lg" icon={<Car className="size-5" />}>
                  Book a ride
                </Button>
              </Link>
              <Link to={user?.role === "DRIVER" ? "/drive" : "/signup/driver"}>
                <Button size="lg" className="bg-white text-[#0b0f19] hover:bg-white/90">
                  Drive with us
                </Button>
              </Link>
              <Link to="/login">
                <Button size="lg" variant="ghost" className="text-white hover:bg-white/10">
                  Operations console <ArrowRight className="size-4" />
                </Button>
              </Link>
            </div>
          </div>

          <div className="relative hidden md:block">
            <div className="absolute -inset-6 rounded-[40px] bg-emerald-400/10 blur-2xl" />
            <div className="relative rounded-[32px] border border-white/10 bg-white/5 p-5 backdrop-blur">
              <div className="rounded-2xl bg-white p-4 text-[#0b0f19] shadow-2xl">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs text-slate-500">Driver arriving in</div>
                    <div className="text-2xl font-bold">4 min</div>
                  </div>
                  <div className="rounded-xl bg-slate-900 px-3 py-2 text-center text-white">
                    <div className="text-[10px] tracking-widest text-slate-400 uppercase">PIN</div>
                    <div className="font-mono text-lg font-bold tracking-[0.3em]">4821</div>
                  </div>
                </div>
                <div className="mt-4 flex items-center gap-3 rounded-xl bg-slate-50 p-3">
                  <div className="flex size-10 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-700 font-semibold text-white">KR</div>
                  <div className="flex-1">
                    <div className="font-semibold">Karthik R · 4.92 ★</div>
                    <div className="text-xs text-slate-500">White Maruti Suzuki Swift · TN 09 AB 1234</div>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                  {[
                    ["Mini", "₹176"],
                    ["Sedan", "₹221"],
                    ["Auto", "₹128"],
                  ].map(([name, price], i) => (
                    <div key={name} className={`rounded-xl border p-2 ${i === 0 ? "border-emerald-500 bg-emerald-50" : "border-slate-200"}`}>
                      <div className="font-semibold">{name}</div>
                      <div className="text-slate-500">{price}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 text-white">
                {[
                  ["3", "cities live"],
                  ["5", "ride types"],
                  ["100+", "REST endpoints"],
                ].map(([v, l]) => (
                  <div key={l} className="rounded-2xl border border-white/10 bg-white/5 p-3">
                    <div className="text-lg font-bold">{v}</div>
                    <div className="text-[11px] text-white/60">{l}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-5 py-20">
        <div className="mb-10 max-w-2xl">
          <span className="text-xs font-semibold tracking-widest text-brand uppercase">Three apps, one platform</span>
          <h2 className="mt-2 text-3xl font-bold tracking-tight">Everything a ride-hailing company runs on</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="card p-5 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-float)]">
              <div className="mb-4 flex size-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong dark:text-brand-fg">
                <Icon className="size-5" />
              </div>
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-surface-2">
        <div className="mx-auto max-w-6xl px-5 py-14">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="size-4 text-brand" /> Built with
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {STACK.map((tech) => (
              <span key={tech} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm font-medium">
                {tech}
              </span>
            ))}
          </div>
          <div className="mt-6 flex flex-wrap gap-3 text-sm">
            <a className="font-semibold text-brand-strong hover:underline" href="/api/docs/">
              REST API docs (Swagger) →
            </a>
            <a className="font-semibold text-brand-strong hover:underline" href="/api/redoc/">
              ReDoc →
            </a>
            <a className="font-semibold text-brand-strong hover:underline" href="/admin/">
              Django admin →
            </a>
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-sm text-muted">
        <Logo />
        <span className="flex flex-wrap gap-4">
          <Link to="/status" className="hover:text-fg">Service status</Link>
          <Link to="/grievance-officer" className="hover:text-fg">Grievance officer</Link>
          <span>A portfolio project · fares, drivers and trips are simulated.</span>
        </span>
      </footer>
    </div>
  );
}
