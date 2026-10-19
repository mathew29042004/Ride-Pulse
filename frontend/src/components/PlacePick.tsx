/** A plain search box for choosing one place (office, home), using our own place search. */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Input } from "@/components/ui";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

export interface Picked {
  name: string;
  address: string;
  lat: number;
  lng: number;
}

export function PlacePick({ value, onChange, placeholder }: { value: Picked | null; onChange: (p: Picked) => void; placeholder?: string }) {
  const [q, setQ] = useState("");
  const results = useQuery({
    queryKey: ["places", "pick", q],
    queryFn: () => api.get<Picked[]>(`places/?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
  });
  return (
    <div>
      {value && <div className="mb-1 text-sm font-semibold">{value.name} <span className="font-normal text-muted">{value.address}</span></div>}
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder ?? t("Search for a place")} />
      {q.trim().length >= 2 && (
        <div className="mt-1 max-h-48 overflow-auto rounded-xl border border-line">
          {results.data?.slice(0, 6).map((p) => (
            <button key={`${p.lat},${p.lng}`} onClick={() => { onChange(p); setQ(""); }} className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-2">
              {p.name} <span className="text-xs text-muted">{p.address}</span>
            </button>
          ))}
          {results.data?.length === 0 && <div className="px-3 py-2 text-xs text-muted">{t("Nothing found")}</div>}
        </div>
      )}
    </div>
  );
}
