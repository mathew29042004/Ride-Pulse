/** Public: the grievance officer's name and contact details, as the Aggregator Guidelines require. */

import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { Link } from "react-router";

import { api } from "@/lib/api";

interface Officer {
  name: string;
  title: string;
  email: string;
  phone: string;
  hours: string;
  address: string;
  acknowledge_within_hours: number;
  resolve_within_days: number;
}

export default function GrievanceOfficer() {
  const q = useQuery({ queryKey: ["grievance-officer"], queryFn: () => api.get<Officer>("grievance-officer/") });
  const o = q.data;
  return (
    <main className="mx-auto min-h-full max-w-xl bg-canvas px-5 py-10 text-fg">
      <h1 className="flex items-center gap-2 text-2xl font-bold"><Scale className="size-6" /> Grievance officer</h1>
      <p className="mt-2 text-sm text-muted">
        Riders and drivers can raise a grievance in the app (Account → Grievances) or by email or phone. We acknowledge every grievance within {o?.acknowledge_within_hours ?? 48} hours and resolve it in writing within {o?.resolve_within_days ?? 15} days. If you're not satisfied, you can escalate it to our appellate officer, or approach your state transport authority or the consumer commission.
      </p>
      {o && (
        <div className="mt-5 rounded-2xl border border-line bg-surface p-4 text-sm">
          <div className="text-lg font-semibold">{o.name}</div>
          <div className="text-muted">{o.title}</div>
          <div className="mt-2"><a className="text-brand" href={`mailto:${o.email}`}>{o.email}</a> · {o.phone}</div>
          <div className="text-muted">{o.hours}</div>
          <div className="mt-2 text-muted">{o.address}</div>
        </div>
      )}
      <Link to="/" className="mt-6 inline-block text-sm text-brand">← Ride Pulse</Link>
    </main>
  );
}
