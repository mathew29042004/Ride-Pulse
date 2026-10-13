/**
 * Sign in with a mobile number and an SMS code, the way ride-hailing apps do. New numbers
 * finish signing up with just a name.
 */

import { ArrowLeft, Smartphone } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";

type Tokens = { access: string; refresh: string; user: User };

export function PhoneLogin({ onDone }: { onDone: (user: User) => void }) {
  const { acceptTokens } = useAuth();
  const [step, setStep] = useState<"phone" | "code" | "name">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [signupToken, setSignupToken] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step !== "code") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [step]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const sendCode = () =>
    run(async () => {
      const res = await api.post<{ phone: string; resend_in: number; debug_code?: string }>("auth/otp/request/", { phone });
      setPhone(res.phone);
      setStep("code");
      setCode("");
      setResendAt(Date.now() + res.resend_in * 1000);
      setNow(Date.now());
      // Development only: no SMS provider is configured, so the server hands the code back.
      if (res.debug_code) toast.info(`Demo SMS: your Ride Pulse code is ${res.debug_code}`, { duration: 15_000 });
      setTimeout(() => codeInput.current?.focus(), 50);
    });

  const verify = (value = code) =>
    run(async () => {
      const res = await api.post<{ new_user: true; signup_token: string } | ({ new_user: false } & Tokens)>("auth/otp/verify/", { phone, code: value });
      if (res.new_user) {
        setSignupToken(res.signup_token);
        setStep("name");
        return;
      }
      acceptTokens(res);
      onDone(res.user);
    });

  const finishSignup = () =>
    run(async () => {
      const [first, ...rest] = name.trim().split(/\s+/);
      const res = await api.post<Tokens>("auth/otp/signup/", { signup_token: signupToken, first_name: first, last_name: rest.join(" ") });
      acceptTokens(res);
      toast.success(`Welcome to Ride Pulse, ${res.user.first_name}!`);
      onDone(res.user);
    });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (step === "phone") sendCode();
    else if (step === "code") verify();
    else finishSignup();
  };
  const wait = Math.max(0, Math.ceil((resendAt - now) / 1000));

  return (
    <form onSubmit={submit} className="space-y-4">
      {step === "phone" && (
        <>
          <Field label="Mobile number" error={error}>
            <div className="flex items-stretch gap-2">
              <span className="flex items-center gap-1.5 rounded-xl border border-line bg-surface-2 px-3 text-sm font-semibold">🇮🇳 +91</span>
              <Input
                type="tel"
                inputMode="numeric"
                autoComplete="tel-national"
                required
                autoFocus
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/[^\d\s-]/g, "").slice(0, 12))}
                placeholder="98765 43210"
              />
            </div>
          </Field>
          <Button type="submit" block size="lg" loading={busy} icon={<Smartphone className="size-4" />}>
            Send code
          </Button>
          <p className="text-center text-xs text-muted">We'll text you a 6-digit code. New here? You'll create an account in seconds.</p>
        </>
      )}

      {step === "code" && (
        <>
          <button type="button" onClick={() => setStep("phone")} className="flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ArrowLeft className="size-4" /> +91 {phone}
          </button>
          <Field label="Enter the 6-digit code" error={error}>
            <Input
              ref={codeInput}
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => {
                const value = e.target.value.replace(/\D/g, "").slice(0, 6);
                setCode(value);
                if (value.length === 6) verify(value); // like apps do: no extra tap needed
              }}
              placeholder="••••••"
              className="text-center font-mono text-2xl font-bold tracking-[0.5em]"
              aria-label="Login code"
            />
          </Field>
          <Button type="submit" block size="lg" loading={busy} disabled={code.length !== 6}>
            Verify
          </Button>
          <p className="text-center text-xs text-muted">
            {wait > 0 ? (
              `Resend code in ${wait}s`
            ) : (
              <button type="button" onClick={sendCode} className="font-semibold text-fg underline">
                Resend code
              </button>
            )}
          </p>
        </>
      )}

      {step === "name" && (
        <>
          <div>
            <h2 className="text-lg font-bold">Welcome to Ride Pulse</h2>
            <p className="text-sm text-muted">+91 {phone} is verified. What should drivers call you?</p>
          </div>
          <Field label="Your name" error={error}>
            <Input autoFocus required value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" autoComplete="name" />
          </Field>
          <Button type="submit" block size="lg" loading={busy} disabled={!name.trim()}>
            Create account
          </Button>
        </>
      )}
    </form>
  );
}
