/** Two-step sign-in for staff: the code box after the password, and the Security settings. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Input, Modal } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import { t } from "@/lib/i18n";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : t("Something went wrong."));

/** After a correct password: the 6-digit code (or a recovery code) finishes signing in. */
export function TwoStepPrompt({ challenge, onDone, onCancel }: { challenge: string; onDone: (user: User) => void; onCancel: () => void }) {
  const { acceptTokens } = useAuth();
  const [code, setCode] = useState("");
  const verify = useMutation({
    mutationFn: () => api.post<{ access: string; refresh: string; user: User }>("auth/2fa/verify/", { challenge, code }),
    onSuccess: (data) => {
      acceptTokens(data);
      onDone(data.user);
    },
    onError: (err) => toast.error(err instanceof ApiError && err.status === 400 ? t("That code didn't match.") : errorText(err)),
  });
  return (
    <Modal
      open
      onClose={onCancel}
      title={t("Two-step sign-in")}
      footer={
        <Button block loading={verify.isPending} disabled={code.replace(/\D/g, "").length < 6} onClick={() => verify.mutate()}>
          {t("Verify")}
        </Button>
      }
    >
      <p className="mb-3 text-sm text-muted">{t("Enter the 6-digit code from your authenticator app, or one of your recovery codes.")}</p>
      <Input autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && verify.mutate()} placeholder="123 456" aria-label={t("Code")} />
    </Modal>
  );
}

interface Status {
  enabled: boolean;
  required: boolean;
  recovery_codes_left: number;
}

/** Ops → Security: turn two-step sign-in on or off. */
export function TwoStepSettings() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const status = useQuery({ queryKey: ["2fa"], queryFn: () => api.get<Status>("auth/2fa/") });
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [turningOff, setTurningOff] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["2fa"] });
  const begin = useMutation({ mutationFn: () => api.post<{ secret: string; uri: string }>("auth/2fa/"), onSuccess: setSetup, onError: (e) => toast.error(errorText(e)) });
  const enable = useMutation({
    mutationFn: () => api.post<{ recovery_codes: string[] }>("auth/2fa/enable/", { code }),
    onSuccess: (r) => {
      setRecovery(r.recovery_codes);
      setSetup(null);
      setCode("");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const disable = useMutation({
    mutationFn: () => api.post("auth/2fa/disable/", { code }),
    onSuccess: () => {
      toast.success(t("Two-step sign-in is off"));
      setTurningOff(false);
      setCode("");
      refresh();
    },
    onError: (e) => toast.error(errorText(e)),
  });
  const s = status.data;
  if (!s) return null;
  return (
    <div className="rounded-2xl border border-line p-4">
      <div className="flex items-start gap-3">
        <ShieldCheck className={s.enabled ? "size-6 text-brand" : "size-6 text-muted"} />
        <div className="flex-1">
          <div className="font-semibold">Two-step sign-in {s.enabled ? "is on" : "is off"}</div>
          <p className="text-sm text-muted">
            {s.enabled
              ? `After your password you enter a code from your authenticator app. ${s.recovery_codes_left} recovery codes left.`
              : s.required
                ? `Required for your role (${user?.role.replaceAll("_", " ").toLowerCase()}): a stolen password alone won't open your account.`
                : t("Recommended: a stolen password alone won't open your account.")}
          </p>
        </div>
        {s.enabled ? (
          <Button variant="outline" size="sm" onClick={() => setTurningOff(true)}>
            {t("Turn off")}
          </Button>
        ) : (
          <Button size="sm" icon={<KeyRound className="size-4" />} loading={begin.isPending} onClick={() => begin.mutate()}>
            {t("Set up")}
          </Button>
        )}
      </div>

      {setup && (
        <div className="mt-4 space-y-3 rounded-xl bg-surface-2 p-3 text-sm">
          <p>
            {t("1. In Google Authenticator or Microsoft Authenticator, choose")} <b>Add account → Enter a setup key</b>, and type this key (time-based):
          </p>
          <code className="block select-all break-all rounded-lg bg-surface p-2 font-mono text-base tracking-wider">{setup.secret.match(/.{1,4}/g)?.join(" ")}</code>
          <p className="text-xs text-muted">
            On a phone, you can tap{" "}
            <a className="text-brand" href={setup.uri}>
              this link
            </a>{" "}
            to add it directly.
          </p>
          <p>{t("2. Enter the 6-digit code it shows:")}</p>
          <div className="flex gap-2">
            <Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123 456" aria-label={t("Code")} />
            <Button loading={enable.isPending} disabled={code.replace(/\D/g, "").length < 6} onClick={() => enable.mutate()}>
              {t("Turn on")}
            </Button>
          </div>
        </div>
      )}

      {recovery && (
        <Modal open onClose={() => setRecovery(null)} title={t("Save your recovery codes")} footer={<Button block onClick={() => setRecovery(null)}>{t("I've saved them")}</Button>}>
          <p className="mb-2 text-sm">{t("If you lose your phone, each of these signs you in once. They won't be shown again.")}</p>
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-surface-2 p-3 font-mono text-sm">
            {recovery.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
        </Modal>
      )}

      {turningOff && (
        <Modal open onClose={() => setTurningOff(false)} title={t("Turn off two-step sign-in")} footer={<Button block variant="danger" loading={disable.isPending} onClick={() => disable.mutate()}>{t("Turn off")}</Button>}>
          <p className="mb-2 text-sm">{t("Enter a current code (or a recovery code) to confirm.")}</p>
          <Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} aria-label={t("Code")} />
        </Modal>
      )}
    </div>
  );
}
