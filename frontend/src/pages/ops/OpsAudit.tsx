import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Fragment, useState } from "react";

import { Badge, Card, Input, PageHeader, Pagination, Select, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { AuditEntry, Paginated } from "@/lib/types";
import { rowLink } from "@/lib/rowLink";

const ACTION_TONES: Record<string, "brand" | "info" | "warning" | "danger" | "neutral"> = {
  CREATE: "brand",
  UPDATE: "info",
  TRANSITION: "warning",
  DELETE: "danger",
  ACTION: "neutral",
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "∅";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function OpsAudit() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const qs = new URLSearchParams({ page: String(page), search, entity_type: entity, action });
  const logs = useQuery({ queryKey: ["audit", qs.toString()], queryFn: () => api.get<Paginated<AuditEntry>>(`audit-logs/?${qs}`) });

  return (
    <>
      <PageHeader title="Audit trail" subtitle="Append-only history of who changed what, with field-level diffs and request IDs" />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Record, message or request ID" className="pl-9" />
          </div>
          <Select value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }} className="!w-48">
            <option value="">All records</option>
            {["rides.trip", "drivers.driverprofile", "drivers.vehicle", "riders.riderprofile", "support.supportticket"].map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
          <Select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} className="!w-40">
            <option value="">All actions</option>
            {Object.keys(ACTION_TONES).map((a) => (
              <option key={a}>{a}</option>
            ))}
          </Select>
        </div>
        {logs.error && <p className="px-5 py-10 text-center text-sm text-muted">{(logs.error as Error).message}</p>}
        <Table>
          <thead>
            <tr>
              <Th>When</Th>
              <Th>Actor</Th>
              <Th>Action</Th>
              <Th>Record</Th>
              <Th>Change</Th>
            </tr>
          </thead>
          <tbody>
            {logs.data?.results.map((e) => {
              const fields = Object.keys(e.changes ?? {});
              return (
                <Fragment key={e.id}>
                  <tr {...rowLink(() => setOpen(open === e.id ? null : e.id))} aria-expanded={open === e.id} className="cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2">
                    <Td className="whitespace-nowrap">{dateTime(e.created_at)}</Td>
                    <Td>{e.actor_email ?? <span className="text-muted">system</span>}</Td>
                    <Td>
                      <Badge tone={ACTION_TONES[e.action] ?? "neutral"}>{e.action.toLowerCase()}</Badge>
                    </Td>
                    <Td>
                      <div className="font-medium">{e.entity_label}</div>
                      <div className="font-mono text-[11px] text-muted">
                        {e.entity_type}#{e.entity_id}
                      </div>
                    </Td>
                    <Td className="max-w-80 truncate text-muted">{e.message || (fields.length ? `${fields.length} field${fields.length > 1 ? "s" : ""}: ${fields.slice(0, 4).join(", ")}` : "—")}</Td>
                  </tr>
                  {open === e.id && fields.length > 0 && (
                    <tr>
                      <td colSpan={5} className="border-b border-line bg-surface-2 px-6 py-3">
                        <div className="grid gap-1 font-mono text-xs">
                          {fields.map((f) => (
                            <div key={f}>
                              <span className="font-semibold">{f}</span>: <span className="text-danger line-through">{show(e.changes[f][0])}</span> → <span className="text-brand-strong">{show(e.changes[f][1])}</span>
                            </div>
                          ))}
                          {e.request_id && <div className="mt-1 text-muted">request {e.request_id} · ip {e.ip_address ?? "—"}</div>}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
        {logs.data && <Pagination page={page} count={logs.data.count} onChange={setPage} />}
      </Card>
    </>
  );
}
