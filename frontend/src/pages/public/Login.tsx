import { ArrowRight, Briefcase, Building2, Car, CarTaxiFront, Crown, NotebookPen, Headset, LayoutDashboard, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Logo } from "@/components/Logo";
import { PhoneLogin } from "@/components/PhoneLogin";
import { Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { TwoStepPrompt } from "@/components/TwoStep";
import { homeFor, TwoFactorRequired, useAuth } from "@/lib/auth";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "@/lib/demo";

const ICONS = { Rider: Car, Driver: CarTaxiFront, Operations: LayoutDashboard, Support: Headset, Business: Briefcase, "Fleet owner": Building2, Admin: ShieldCheck, Commander: Crown, "Chief of staff": NotebookPen };

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [method, setMethod] = useState<"phone" | "email">("phone");
  const [challenge, setChallenge] = useState<string | null>(null);

  // ?switch=1 shows the form even when signed in, to change accounts in this tab.
  if (user && !params.get("switch")) return <Navigate to={params.get("next") ?? homeFor(user.role)} replace />;

  async function signIn(address: string, secret: string, key: string) {
    setBusy(key);
    setError(null);
    try {
      const me = await login(address, secret);
      toast.success(`Welcome back, ${me.first_name || me.email}`);
      navigate(params.get("next") ?? homeFor(me.role), { replace: true });
    } catch (err) {
      if (err instanceof TwoFactorRequired) {
        setChallenge(err.challenge);
        return;
      }
      setError(err instanceof ApiError && err.status === 401 ? "Wrong email or password." : (err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    signIn(email, password, "form");
  }

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      {challenge && (
        <TwoStepPrompt
          challenge={challenge}
          onCancel={() => setChallenge(null)}
          onDone={(me) => {
            toast.success(`Welcome back, ${me.first_name || me.email}`);
            navigate(params.get("next") ?? homeFor(me.role), { replace: true });
          }}
        />
      )}
      <div className="relative hidden overflow-hidden bg-[#070a10] p-10 text-white lg:flex lg:flex-col">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_10%_0%,rgb(16_185_129/0.35),transparent_50%),radial-gradient(ellipse_at_100%_100%,rgb(14_165_233/0.2),transparent_45%)]" />
        <Link to="/" className="relative">
          <Logo light />
        </Link>
        <div className="relative mt-auto">
          <h2 className="text-3xl font-bold tracking-tight">Try every side of the marketplace.</h2>
          <p className="mt-3 max-w-md text-white/70">
            Sign in with a demo account. Open the rider app in one tab and the driver app in another to book and accept your own ride.
          </p>
          <div className="mt-8 grid gap-3">
            {DEMO_ACCOUNTS.map((account) => {
              const Icon = ICONS[account.label];
              return (
                <button
                  key={account.email}
                  onClick={() => signIn(account.email, DEMO_PASSWORD, account.email)}
                  disabled={busy !== null}
                  className="group flex items-center gap-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-emerald-400/50 hover:bg-white/10 disabled:opacity-60"
                >
                  <span className="flex size-10 items-center justify-center rounded-xl bg-emerald-400/15 text-emerald-300">
                    <Icon className="size-5" />
                  </span>
                  <span className="flex-1">
                    <span className="block font-semibold">{account.label}</span>
                    <span className="block text-xs text-white/60">{account.description}</span>
                  </span>
                  <ArrowRight className="size-4 text-white/40 transition group-hover:translate-x-0.5 group-hover:text-white" />
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center bg-surface p-6">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-10 inline-block lg:hidden">
            <Logo />
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Log in</h1>
          <p className="mt-1 text-sm text-muted">Riders and drivers can use their phone; staff sign in with email.</p>
          <div className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-surface-3 p-1 text-sm font-semibold" role="tablist">
            {(["phone", "email"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={method === m}
                onClick={() => setMethod(m)}
                className={method === m ? "rounded-lg bg-surface py-2 shadow-sm" : "rounded-lg py-2 text-muted"}
              >
                {m === "phone" ? "Phone" : "Email"}
              </button>
            ))}
          </div>
          {method === "phone" ? (
            <div className="mt-6">
              <PhoneLogin
                onDone={(me) => {
                  toast.success(`Welcome, ${me.first_name || "rider"}`);
                  navigate(params.get("next") ?? homeFor(me.role), { replace: true });
                }}
              />
            </div>
          ) : (
            <form onSubmit={onSubmit} className="mt-6 space-y-4">
              <Field label="Email">
                <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </Field>
              <Field label="Password" error={error}>
                <Input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                />
              </Field>
              <Button type="submit" block size="lg" loading={busy === "form"}>
                Continue
              </Button>
            </form>
          )}
          <div className="mt-6 grid gap-2 lg:hidden">
            <p className="text-xs font-semibold tracking-wide text-muted uppercase">Demo accounts</p>
            <div className="grid grid-cols-3 gap-2">
              {DEMO_ACCOUNTS.slice(0, 3).map((account) => (
                <Button
                  key={account.email}
                  variant="outline"
                  size="sm"
                  loading={busy === account.email}
                  onClick={() => signIn(account.email, DEMO_PASSWORD, account.email)}
                >
                  {account.label}
                </Button>
              ))}
            </div>
          </div>
          <p className="mt-8 text-center text-sm text-muted">
            New here?{" "}
            <Link className="font-semibold text-fg hover:underline" to="/signup">
              Create a rider account
            </Link>{" "}
            or{" "}
            <Link className="font-semibold text-fg hover:underline" to="/signup/driver">
              become a driver
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
