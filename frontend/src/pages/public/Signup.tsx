import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Logo } from "@/components/Logo";
import { Button, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import type { City, User } from "@/lib/types";

export default function Signup({ kind }: { kind: "rider" | "driver" }) {
  const { user, acceptTokens } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    password: "",
    referral_code: (params.get("ref") ?? "").toUpperCase(), // from an invite link
    city: "chennai",
    license_number: "",
    license_expiry: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ field: string | null; message: string } | null>(null);
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/"), enabled: kind === "driver" });

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const base = { first_name: form.first_name, last_name: form.last_name, email: form.email, phone: form.phone, password: form.password };
    const body =
      kind === "rider"
        ? { ...base, referral_code: form.referral_code }
        : { ...base, city: form.city, license_number: form.license_number, license_expiry: form.license_expiry };
    try {
      const data = await api.post<{ access: string; refresh: string; user: User }>(`auth/register/${kind}/`, body);
      acceptTokens(data);
      toast.success(kind === "rider" ? "Welcome to Ride Pulse!" : "Account created. Upload your documents to start driving.");
      navigate(kind === "rider" ? "/ride" : "/drive/documents", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? { field: err.field, message: err.message } : { field: null, message: "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  const fieldError = (name: string) => (error?.field === name ? error.message : null);

  return (
    <div className="flex min-h-full items-center justify-center bg-canvas p-6">
      <div className="card w-full max-w-md p-7">
        <Link to="/">
          <Logo />
        </Link>
        <h1 className="mt-6 text-2xl font-bold tracking-tight">{kind === "rider" ? "Create your rider account" : "Drive with Ride Pulse"}</h1>
        <p className="mt-1 text-sm text-muted">
          {kind === "rider" ? "Book rides in under a minute." : "Earn on your schedule. We'll verify your documents before your first trip."}
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name" error={fieldError("first_name")}>
              <Input required value={form.first_name} onChange={set("first_name")} />
            </Field>
            <Field label="Last name">
              <Input value={form.last_name} onChange={set("last_name")} />
            </Field>
          </div>
          <Field label="Email" error={fieldError("email")}>
            <Input type="email" required value={form.email} onChange={set("email")} />
          </Field>
          <Field label="Mobile number" error={fieldError("phone")} hint="10 digits, e.g. 9876543210">
            <Input inputMode="tel" value={form.phone} onChange={set("phone")} />
          </Field>
          <Field label="Password" error={fieldError("password")} hint="At least 8 characters">
            <Input type="password" required minLength={8} value={form.password} onChange={set("password")} />
          </Field>
          {kind === "rider" ? (
            <Field label="Referral code (optional)" error={fieldError("referral_code")}>
              <Input value={form.referral_code} onChange={set("referral_code")} placeholder="RPXXXXXX" />
            </Field>
          ) : (
            <>
              <Field label="City">
                <Select value={form.city} onChange={set("city")}>
                  {(cities.data ?? []).map((c) => (
                    <option key={c.slug} value={c.slug}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Licence number" error={fieldError("license_number")}>
                  <Input required value={form.license_number} onChange={set("license_number")} placeholder="TN0120190001234" />
                </Field>
                <Field label="Licence expiry" error={fieldError("license_expiry")}>
                  <Input type="date" required value={form.license_expiry} onChange={set("license_expiry")} />
                </Field>
              </div>
            </>
          )}
          {error && !error.field && <p className="text-sm text-danger">{error.message}</p>}
          {error?.field && !["first_name", "email", "phone", "password", "referral_code", "license_number", "license_expiry"].includes(error.field) && (
            <p className="text-sm text-danger">{error.message}</p>
          )}
          <Button type="submit" block size="lg" loading={busy}>
            Create account
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted">
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-fg hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}
