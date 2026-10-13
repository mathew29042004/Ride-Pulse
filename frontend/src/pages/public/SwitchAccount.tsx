import { ArrowRight, LogIn } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { Logo } from "@/components/Logo";
import { Avatar, Button } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "@/lib/demo";
import type { Role } from "@/lib/types";

const APP_NAMES: Record<string, string> = { "/ride": "rider app", "/drive": "driver app", "/ops": "operations console" };
const DEMO_NOUN: Record<string, string> = { Operations: "operations manager", Support: "support agent" };
const ROLE_NAMES: Record<Role, string> = {
  RIDER: "a rider",
  DRIVER: "a driver",
  OPS_MANAGER: "an operations manager",
  SUPPORT_AGENT: "a support agent",
  ADMIN: "an admin",
};

/**
 * Shown when someone opens an app their account can't use (e.g. the driver app while signed in
 * as a rider), instead of silently sending them back to their own app.
 */
export default function SwitchAccount({ app, roles }: { app: string; roles: Role[] }) {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const demo = DEMO_ACCOUNTS.filter((a) =>
    roles.includes(({ Rider: "RIDER", Driver: "DRIVER", Operations: "OPS_MANAGER", Support: "SUPPORT_AGENT", Admin: "ADMIN" } as const)[a.label]),
  );

  async function signIn(email: string) {
    setBusy(email);
    try {
      const me = await login(email, DEMO_PASSWORD);
      toast.success(`Signed in as ${me.first_name} in this tab`);
      navigate(app, { replace: true });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!user) return null;
  return (
    <div className="flex min-h-full items-center justify-center bg-canvas p-6">
      <div className="card w-full max-w-md p-7 text-center">
        <Logo className="justify-center" />
        <h1 className="mt-6 text-xl font-bold">The {APP_NAMES[app]} needs a different account</h1>
        <div className="mx-auto mt-4 flex w-fit items-center gap-3 rounded-2xl bg-surface-2 px-4 py-2.5 text-left">
          <Avatar name={`${user.first_name} ${user.last_name}`} size={36} />
          <div className="text-sm">
            <div className="font-semibold">
              {user.first_name} {user.last_name}
            </div>
            <div className="text-xs text-muted">Signed in as {ROLE_NAMES[user.role]}</div>
          </div>
        </div>
        <div className="mt-6 space-y-2">
          {demo.map((account) => (
            <Button key={account.email} block size="lg" icon={<LogIn className="size-4" />} loading={busy === account.email} onClick={() => signIn(account.email)}>
              Sign in as the demo {DEMO_NOUN[account.label] ?? account.label.toLowerCase()} in this tab
            </Button>
          ))}
          <Link to={homeFor(user.role)} className="block">
            <Button block variant="outline">
              Back to my app <ArrowRight className="size-4" />
            </Button>
          </Link>
        </div>
        <p className="mt-5 text-xs text-muted">
          Each browser tab keeps its own sign-in, so you can be the rider in one tab and the driver in another.{" "}
          <Link to={`/login?next=${app}&switch=1`} className="font-semibold text-fg underline">
            Use another account
          </Link>
        </p>
      </div>
    </div>
  );
}
