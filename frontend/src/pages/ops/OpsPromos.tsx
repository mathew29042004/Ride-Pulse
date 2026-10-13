import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, Td, Th, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { date, inr } from "@/lib/format";
import type { City, Paginated, Promo } from "@/lib/types";

const blank = { code: "", description: "", discount_type: "PERCENT", value: "20", max_discount: "75", min_fare: "0", days: "30", max_redemptions: "", max_per_rider: "1", first_ride_only: false, city: "" };

export default function OpsPromos() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(blank);
  const promos = useQuery({ queryKey: ["promos"], queryFn: () => api.get<Paginated<Promo>>("promos/?page_size=50") });
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.get<City[]>("cities/") });
  const create = useMutation({
    mutationFn: () => {
      const now = new Date();
      return api.post("promos/", {
        code: form.code,
        description: form.description,
        discount_type: form.discount_type,
        value: form.value,
        max_discount: form.max_discount || null,
        min_fare: form.min_fare || "0",
        valid_from: now.toISOString(),
        valid_until: new Date(now.getTime() + Number(form.days) * 86_400_000).toISOString(),
        max_redemptions: form.max_redemptions ? Number(form.max_redemptions) : null,
        max_per_rider: Number(form.max_per_rider),
        first_ride_only: form.first_ride_only,
        city: form.city ? Number(form.city) : null,
        ride_types: [],
      });
    },
    onSuccess: () => {
      toast.success("Promo created");
      setOpen(false);
      setForm(blank);
      qc.invalidateQueries({ queryKey: ["promos"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const toggle = useMutation({
    mutationFn: (p: Promo) => api.patch(`promos/${p.id}/`, { is_active: !p.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["promos"] }),
  });
  const set = (key: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <>
      <PageHeader title="Promotions" subtitle="Discounts are funded by the platform; drivers are always paid in full" actions={<Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>New promo</Button>} />
      <Card>
        <Table>
          <thead>
            <tr>
              <Th>Code</Th>
              <Th>Discount</Th>
              <Th>Rules</Th>
              <Th>Valid until</Th>
              <Th className="text-right">Used</Th>
              <Th className="text-right">Given</Th>
              <Th>Active</Th>
            </tr>
          </thead>
          <tbody>
            {promos.data?.results.map((p) => (
              <tr key={p.id}>
                <Td>
                  <div className="font-mono font-bold">{p.code}</div>
                  <div className="text-xs text-muted">{p.description}</div>
                </Td>
                <Td>
                  {p.discount_type === "PERCENT" ? `${Number(p.value)}%` : inr(p.value, { whole: true })}
                  {p.max_discount && <span className="text-xs text-muted"> · max {inr(p.max_discount, { whole: true })}</span>}
                </Td>
                <Td className="space-x-1">
                  {p.first_ride_only && <Badge tone="info">first ride</Badge>}
                  {p.city && <Badge>{cities.data?.find((c) => c.id === p.city)?.name}</Badge>}
                  <Badge>{p.max_per_rider}× per rider</Badge>
                </Td>
                <Td>{date(p.valid_until)}</Td>
                <Td className="text-right">
                  {p.usage.redemptions}
                  {p.max_redemptions ? ` / ${p.max_redemptions}` : ""}
                </Td>
                <Td className="text-right">{inr(p.usage.discount_given, { whole: true })}</Td>
                <Td>
                  <Toggle checked={p.is_active} onChange={() => toggle.mutate(p)} label="Active" />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Modal open={open} onClose={() => setOpen(false)} title="New promo code" footer={<Button onClick={() => create.mutate()} loading={create.isPending} disabled={!form.code || !form.description}>Create</Button>}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Code">
            <Input value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))} placeholder="MONSOON25" />
          </Field>
          <Field label="City">
            <Select value={form.city} onChange={set("city")}>
              <option value="">All cities</option>
              {cities.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Description" className="col-span-2">
            <Input value={form.description} onChange={set("description")} placeholder="25% off rides during the monsoon" />
          </Field>
          <Field label="Type">
            <Select value={form.discount_type} onChange={set("discount_type")}>
              <option value="PERCENT">Percent</option>
              <option value="FLAT">Flat amount</option>
            </Select>
          </Field>
          <Field label={form.discount_type === "PERCENT" ? "Percent off" : "Rupees off"}>
            <Input type="number" value={form.value} onChange={set("value")} />
          </Field>
          <Field label="Max discount (₹)">
            <Input type="number" value={form.max_discount} onChange={set("max_discount")} />
          </Field>
          <Field label="Minimum fare (₹)">
            <Input type="number" value={form.min_fare} onChange={set("min_fare")} />
          </Field>
          <Field label="Valid for (days)">
            <Input type="number" value={form.days} onChange={set("days")} />
          </Field>
          <Field label="Total redemptions">
            <Input type="number" value={form.max_redemptions} onChange={set("max_redemptions")} placeholder="Unlimited" />
          </Field>
          <Field label="Per rider">
            <Input type="number" value={form.max_per_rider} onChange={set("max_per_rider")} />
          </Field>
          <label className="flex items-center gap-3 self-end pb-2 text-sm font-medium">
            <Toggle checked={form.first_ride_only} onChange={(v) => setForm((f) => ({ ...f, first_ride_only: v }))} /> First ride only
          </label>
        </div>
      </Modal>
    </>
  );
}
