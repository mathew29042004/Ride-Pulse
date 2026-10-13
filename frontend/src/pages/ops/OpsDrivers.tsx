import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { Avatar, Card, Input, PageHeader, Pagination, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import { useOps } from "@/layouts/OpsLayout";
import { api } from "@/lib/api";
import { ago, inr } from "@/lib/format";
import type { Driver, Paginated } from "@/lib/types";

export default function OpsDrivers() {
  const { city } = useOps();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [onboarding, setOnboarding] = useState("");
  const [availability, setAvailability] = useState("");
  const [ordering, setOrdering] = useState("-completed_trips");
  const qs = new URLSearchParams({ page: String(page), search, onboarding_status: onboarding, availability, ordering, city__slug: city });
  const drivers = useQuery({ queryKey: ["drivers", qs.toString()], queryFn: () => api.get<Paginated<Driver>>(`drivers/?${qs}`), refetchInterval: 20_000 });

  return (
    <>
      <PageHeader title="Drivers" subtitle="Fleet quality, availability and compliance" />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Name, email, licence or registration" className="pl-9" />
          </div>
          <Select value={onboarding} onChange={(e) => { setOnboarding(e.target.value); setPage(1); }} className="!w-44">
            <option value="">All onboarding</option>
            {["APPROVED", "UNDER_REVIEW", "PENDING_DOCUMENTS", "SUSPENDED", "REJECTED"].map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ").toLowerCase()}
              </option>
            ))}
          </Select>
          <Select value={availability} onChange={(e) => { setAvailability(e.target.value); setPage(1); }} className="!w-36">
            <option value="">Any status</option>
            <option value="ONLINE">Online</option>
            <option value="ON_TRIP">On trip</option>
            <option value="OFFLINE">Offline</option>
          </Select>
          <Select value={ordering} onChange={(e) => setOrdering(e.target.value)} className="!w-44">
            <option value="-completed_trips">Most trips</option>
            <option value="-rating">Highest rated</option>
            <option value="rating">Lowest rated</option>
            <option value="safety_score">Lowest safety</option>
            <option value="acceptance_rate">Lowest acceptance</option>
            <option value="-created_at">Newest</option>
          </Select>
        </div>
        <Table>
          <thead>
            <tr>
              <Th>Driver</Th>
              <Th>Vehicle</Th>
              <Th>Status</Th>
              <Th className="text-right">Rating</Th>
              <Th className="text-right">Acceptance</Th>
              <Th className="text-right">Safety</Th>
              <Th className="text-right">Trips</Th>
              <Th className="text-right">Wallet</Th>
            </tr>
          </thead>
          <tbody>
            {drivers.data?.results.map((d) => (
              <tr key={d.id} onClick={() => navigate(`/ops/drivers/${d.id}`)} className="cursor-pointer hover:bg-surface-2">
                <Td>
                  <div className="flex items-center gap-3">
                    <Avatar name={d.name} size={34} />
                    <div>
                      <div className="font-semibold">{d.name}</div>
                      <div className="text-xs text-muted">
                        {d.city} · seen {ago(d.location_updated_at)}
                      </div>
                    </div>
                  </div>
                </Td>
                <Td>
                  <div>{d.vehicle ? `${d.vehicle.make} ${d.vehicle.model}` : "—"}</div>
                  <div className="font-mono text-xs text-muted">{d.vehicle?.registration_display}</div>
                </Td>
                <Td>
                  <div className="flex flex-col gap-1">
                    <StatusBadge status={d.onboarding_status} />
                    <StatusBadge status={d.availability} />
                  </div>
                </Td>
                <Td className="text-right">{Number(d.rating).toFixed(2)}</Td>
                <Td className="text-right">{Number(d.acceptance_rate).toFixed(0)}%</Td>
                <Td className="text-right">{d.safety_score ?? "—"}</Td>
                <Td className="text-right">{d.completed_trips}</Td>
                <Td className={`text-right ${Number(d.wallet_balance) < 0 ? "text-danger" : ""}`}>{inr(d.wallet_balance, { whole: true })}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {drivers.data && <Pagination page={page} count={drivers.data.count} onChange={setPage} />}
      </Card>
    </>
  );
}
