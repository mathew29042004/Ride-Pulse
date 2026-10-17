/** Ops → Security: your own two-step sign-in, and (for admins) who still needs to turn it on. */

import { useQuery } from "@tanstack/react-query";

import { TwoStepSettings } from "@/components/TwoStep";
import { Card, CardHeader, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface Coverage {
  staff: number;
  enabled: number;
  required: number;
  required_missing: { id: number; name: string; role: string }[];
}

export default function OpsSecurity() {
  const { can } = useAuth();
  const coverage = useQuery({ queryKey: ["2fa", "coverage"], queryFn: () => api.get<{ two_factor: Coverage }>("platform/health/"), enabled: can("audit.view") });
  const c = coverage.data?.two_factor;
  return (
    <>
      <PageHeader title="Security" subtitle="Two-step sign-in: after your password, a 6-digit code from an authenticator app on your phone. Required for admins and managers." />
      <div className="max-w-2xl space-y-4">
        <TwoStepSettings />
        {c && (
          <Card className="p-4">
            <CardHeader title="Across the team" subtitle={`${c.enabled} of ${c.staff} staff have two-step sign-in on. ${c.required - c.required_missing.length} of ${c.required} who must have it do.`} />
            {c.required_missing.length > 0 ? (
              <ul className="space-y-1 text-sm">
                {c.required_missing.map((p) => (
                  <li key={p.id} className="flex justify-between border-t border-line pt-1 first:border-0">
                    <span>{p.name}</span>
                    <span className="text-xs text-muted">{p.role.replaceAll("_", " ").toLowerCase()} · not set up</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">Everyone who must have it has turned it on.</p>
            )}
          </Card>
        )}
      </div>
    </>
  );
}
