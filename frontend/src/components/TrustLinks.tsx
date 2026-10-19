/** Account rows: help centre, privacy, insurance claims and appeals. */

import { ChevronRight, FileWarning, Gavel, HelpCircle, Scale, ShieldCheck } from "lucide-react";
import { Link } from "react-router";

import { t } from "@/lib/i18n";

export function TrustLinks({ base }: { base: "/ride" | "/drive" }) {
  const rows = [
    { to: `${base}/help`, label: t("Help centre"), icon: HelpCircle },
    { to: `${base}/privacy`, label: t("Privacy and your data"), icon: ShieldCheck },
    { to: `${base}/claims`, label: t("Insurance claims"), icon: FileWarning },
    { to: `${base}/appeals`, label: t("Appeals"), icon: Gavel },
    { to: `${base}/grievances`, label: t("Grievances"), icon: Scale },
  ];
  return (
    <>
      {rows.map(({ to, label, icon: Icon }) => (
        <Link key={to} to={to} className="flex items-center gap-3 py-3.5">
          <Icon className="size-5" />
          <span className="flex-1 font-medium">{label}</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
      ))}
    </>
  );
}
