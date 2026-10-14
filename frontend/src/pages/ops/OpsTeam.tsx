/**
 * The organisation: headcount, an org chart from leadership down to fleet executives (and the
 * driver partners they look after), and a searchable staff directory.
 */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Building2, ChevronDown, ChevronRight, Network, Search, UserRound, Users } from "lucide-react";
import { useState } from "react";

import { Avatar, Badge, Card, CardHeader, Input, PageHeader, Pagination, Segmented, Select, Stat, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import type { Paginated } from "@/lib/types";

interface OrgNode {
  id: number;
  employee_id: string;
  name: string;
  email: string;
  role: string;
  role_label: string;
  title: string;
  department: string;
  department_label: string;
  state: string;
  city: string;
  drivers: number;
  reports: OrgNode[];
}

interface StaffRow {
  id: number;
  employee_id: string;
  name: string;
  email: string;
  role_label: string;
  title: string;
  department: string;
  department_label: string;
  state: string;
  city: string;
  reports_to: string;
  drivers: number;
}

interface Summary {
  employees: number;
  driver_partners: number;
  by_role: Record<string, number>;
  by_department: Record<string, number>;
  by_state: Record<string, number>;
}

const STATES = ["Tamil Nadu", "Kerala", "Karnataka", "Andhra Pradesh"];
const DEPARTMENTS: [string, string][] = [
  ["", "All departments"],
  ["LEADERSHIP", "Leadership"],
  ["OPERATIONS", "City operations"],
  ["RIDES", "Rides"],
  ["SUPPORT", "Customer support"],
  ["MAINTENANCE", "Fleet & maintenance"],
  ["INTERCITY", "Intercity & rentals"],
  ["PARCELS", "Parcels"],
];
const ROLE_TONE: Record<string, "brand" | "info" | "warning" | "neutral"> = {
  ADMIN: "brand",
  REGIONAL_MANAGER: "brand",
  OPS_MANAGER: "info",
  ASSOC_RIDES: "warning",
  ASSOC_SUPPORT: "warning",
  ASSOC_MAINTENANCE: "warning",
  ASSOC_INTERCITY: "warning",
  ASSOC_PARCELS: "warning",
};

function Node({ node, depth }: { node: OrgNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const has = node.reports.length > 0;
  return (
    <div>
      <div className="flex items-center gap-2 rounded-xl px-2 py-1.5 hover:bg-surface-2" style={{ marginLeft: depth * 20 }}>
        <button onClick={() => setOpen((v) => !v)} disabled={!has} className="flex size-5 items-center justify-center text-muted disabled:opacity-0" aria-label={open ? "Collapse" : "Expand"}>
          {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
        <Avatar name={node.name} size={28} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">
            {node.name} <span className="font-normal text-muted">· {node.title}</span>
          </div>
          <div className="truncate text-xs text-muted">
            {node.employee_id}
            {node.city && ` · ${node.city}`}
            {has && ` · ${node.reports.length} direct report${node.reports.length === 1 ? "" : "s"}`}
            {node.drivers > 0 && ` · ${node.drivers} driver partners`}
          </div>
        </div>
        <Badge tone={ROLE_TONE[node.role] ?? "neutral"}>{node.role_label}</Badge>
      </div>
      {open && node.reports.map((child) => <Node key={child.id} node={child} depth={depth + 1} />)}
    </div>
  );
}

export default function OpsTeam() {
  const [view, setView] = useState<"chart" | "directory">("chart");
  const [state, setState] = useState("Tamil Nadu");
  const [department, setDepartment] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const summary = useQuery({ queryKey: ["team", "summary"], queryFn: () => api.get<Summary>("team/summary/") });
  const tree = useQuery({ queryKey: ["team", "tree", state], queryFn: () => api.get<OrgNode[]>(`team/tree/?state=${encodeURIComponent(state)}`), enabled: view === "chart" });
  const directory = useQuery({
    queryKey: ["team", "list", department, search, page],
    queryFn: () => api.get<Paginated<StaffRow>>(`team/?page=${page}&department=${department}&search=${encodeURIComponent(search)}`),
    enabled: view === "directory",
  });
  const s = summary.data;
  const associates = s ? Object.entries(s.by_role).filter(([role]) => role.startsWith("ASSOC_")).reduce((n, [, c]) => n + c, 0) : 0;

  return (
    <>
      <PageHeader title="Team" subtitle="Everyone who runs Ride Pulse, from leadership to the fleet executives who look after driver partners." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Employees" value={s?.employees ?? "—"} icon={<Users className="size-4" />} tone="brand" />
        <Stat label="Driver partners" value={s?.driver_partners ?? "—"} icon={<UserRound className="size-4" />} tone="info" />
        <Stat label="Associate managers" value={associates || "—"} sub="Rides · Support · Fleet · Intercity · Parcels" icon={<Network className="size-4" />} tone="warning" />
        <Stat label="City teams" value={s?.by_role.OPS_MANAGER ?? "—"} sub={s ? Object.entries(s.by_state).map(([st, n]) => `${st.split(" ").map((w) => w[0]).join("")} ${n}`).join(" · ") : ""} icon={<Building2 className="size-4" />} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Segmented
          value={view}
          onChange={(v) => setView(v as "chart" | "directory")}
          options={[
            { value: "chart", label: "Org chart" },
            { value: "directory", label: "Directory" },
          ]}
        />
        {view === "chart" ? (
          <Select value={state} onChange={(e) => setState(e.target.value)} className="!w-auto">
            {STATES.map((st) => (
              <option key={st}>{st}</option>
            ))}
          </Select>
        ) : (
          <>
            <Select value={department} onChange={(e) => { setDepartment(e.target.value); setPage(1); }} className="!w-auto">
              {DEPARTMENTS.map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </Select>
            <div className="relative w-64">
              <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
              <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Name, email, ID or title" className="!py-2 pl-9" />
            </div>
          </>
        )}
      </div>

      {view === "chart" ? (
        <Card className="mt-4 p-3">
          <CardHeader title={`Reporting lines · ${state}`} subtitle="Head of operations → regional manager → associate managers and city managers → support leads, agents and fleet executives." />
          <div className={clsx("px-2 pb-2", tree.isLoading && "opacity-50")}>
            {(tree.data ?? []).map((root) => (
              <Node key={root.id} node={root} depth={0} />
            ))}
          </div>
        </Card>
      ) : (
        <Card className="mt-4 overflow-hidden">
          <Table>
            <thead>
              <tr>
                <Th>Employee</Th>
                <Th>Role</Th>
                <Th>Department</Th>
                <Th>Location</Th>
                <Th>Reports to</Th>
                <Th className="text-right">Drivers</Th>
              </tr>
            </thead>
            <tbody>
              {(directory.data?.results ?? []).map((row) => (
                <tr key={row.id} className="border-t border-line">
                  <Td>
                    <div className="font-semibold">{row.name}</div>
                    <div className="text-xs text-muted">
                      {row.employee_id} · {row.email}
                    </div>
                  </Td>
                  <Td>
                    <div>{row.role_label}</div>
                    <div className="text-xs text-muted">{row.title}</div>
                  </Td>
                  <Td>{row.department_label}</Td>
                  <Td>{[row.city, row.state].filter(Boolean).join(", ") || "—"}</Td>
                  <Td>{row.reports_to || "—"}</Td>
                  <Td className="text-right">{row.drivers || ""}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {directory.data && <Pagination page={page} count={directory.data.count} onChange={setPage} />}
        </Card>
      )}
    </>
  );
}
