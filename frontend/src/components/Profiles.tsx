/** Family and business profiles: manage them in Account, and choose who pays when booking. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Briefcase, Download, Home, Plus, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Field, Input, Modal, Segmented } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";
import { t } from "@/lib/i18n";

export interface PaymentProfile {
  id: number;
  kind: "FAMILY" | "BUSINESS";
  kind_label: string;
  name: string;
  gstin: string;
  owner_name: string;
  role: "OWNER" | "MEMBER" | "INVITED";
  members: { id: number; name: string; phone: string; status: string; monthly_limit: string | null }[];
  spent_this_month: string;
  my_limit: string | null;
  invitation_id: number | null;
  is_admin?: boolean;
  cost_centers?: string[];
  my_cost_center?: string;
}

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

export function useProfiles() {
  return useQuery({ queryKey: ["rider", "profiles"], queryFn: () => api.get<PaymentProfile[]>("rider/profiles/") });
}

/** Booking: personal, or a family/business profile (with a purpose for business). */
export function BillTo({
  value,
  purpose,
  onChange,
  onPurpose,
  costCenter,
  onCostCenter,
}: {
  value: number | null;
  purpose: string;
  onChange: (id: number | null) => void;
  onPurpose: (text: string) => void;
  costCenter?: string;
  onCostCenter?: (centre: string) => void;
}) {
  const usable = (useProfiles().data ?? []).filter((p) => p.role !== "INVITED");
  if (!usable.length) return null;
  const chosen = usable.find((p) => p.id === value);
  return (
    <div className="mt-3">
      <div className="mb-1.5 text-xs font-semibold text-muted">{t("Bill to")}</div>
      <div className="flex flex-wrap gap-1.5">
        <button onClick={() => onChange(null)} className={clsx("rounded-full border px-3 py-1.5 text-xs font-semibold", value === null ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}>
          {t("Personal")}
        </button>
        {usable.map((p) => {
          const Icon = p.kind === "BUSINESS" ? Briefcase : Home;
          return (
            <button key={p.id} onClick={() => onChange(p.id)} className={clsx("flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold", value === p.id ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}>
              <Icon className="size-3.5" /> {p.name}
            </button>
          );
        })}
      </div>
      {chosen && (
        <p className="mt-1.5 text-xs text-muted">
          {t("Paid by {owner}", { owner: chosen.owner_name })}
          {chosen.my_limit && ` · ${t("{spent} of {limit} used this month", { spent: inr(chosen.spent_this_month), limit: inr(chosen.my_limit) })}`}
        </p>
      )}
      {chosen?.kind === "BUSINESS" && <Input value={purpose} onChange={(e) => onPurpose(e.target.value)} maxLength={120} placeholder={t("Purpose of this trip (required)")} className="mt-2 !py-2" />}
      {chosen?.kind === "BUSINESS" && (chosen.cost_centers?.length ?? 0) > 0 && onCostCenter && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {chosen.cost_centers!.map((c) => (
            <button key={c} onClick={() => onCostCenter(c)} className={clsx("rounded-full border px-2.5 py-1 text-xs font-semibold", (costCenter || chosen.my_cost_center) === c ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}>
              {c}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Account: create profiles, invite members, set limits, answer invitations, statements. */
export function ProfilesSection() {
  const qc = useQueryClient();
  const profiles = useProfiles();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ kind: "FAMILY", name: "", gstin: "" });
  const [phones, setPhones] = useState<Record<number, string>>({});
  const refresh = () => qc.invalidateQueries({ queryKey: ["rider", "profiles"] });
  const onError = (err: unknown) => toast.error(errorText(err, "Something went wrong."));
  const create = useMutation({
    mutationFn: () => api.post<PaymentProfile>("rider/profiles/", form),
    onSuccess: () => {
      setCreating(false);
      setForm({ kind: "FAMILY", name: "", gstin: "" });
      refresh();
    },
    onError,
  });
  const invite = useMutation({
    mutationFn: ({ id, phone }: { id: number; phone: string }) => api.post(`rider/profiles/${id}/invite/`, { phone }),
    onSuccess: (_d, v) => {
      setPhones((p) => ({ ...p, [v.id]: "" }));
      toast.success(t("Invitation sent"));
      refresh();
    },
    onError,
  });
  const respond = useMutation({ mutationFn: ({ id, accept }: { id: number; accept: boolean }) => api.post(`rider/profiles/${id}/respond/`, { accept }), onSuccess: refresh, onError });
  const member = useMutation({
    mutationFn: ({ id, ...body }: { id: number; member_id: number; monthly_limit?: number | null; remove?: boolean }) => api.post(`rider/profiles/${id}/member/`, body),
    onSuccess: refresh,
    onError,
  });

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">{t("Family & business")}</h2>
        <button onClick={() => setCreating(true)} className="flex items-center gap-1 text-xs font-semibold text-brand-strong">
          <Plus className="size-3.5" /> {t("New profile")}
        </button>
      </div>
      {(profiles.data ?? []).length === 0 && <p className="mt-2 text-sm text-muted">{t("Pay for your family's rides, or let your company pay for work trips.")}</p>}
      <div className="mt-2 space-y-3">
        {(profiles.data ?? []).map((p) => (
          <div key={p.id} className="rounded-2xl border border-line p-3 text-sm">
            <div className="flex items-center gap-2">
              {p.kind === "BUSINESS" ? <Briefcase className="size-4" /> : <Home className="size-4" />}
              <span className="flex-1 font-semibold">{p.name}</span>
              <span className="text-xs text-muted">{t(p.role === "OWNER" ? t("You pay") : p.role === "INVITED" ? t("Invitation") : "Paid by {owner}", { owner: p.owner_name })}</span>
            </div>
            {p.role === "INVITED" && (
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Button size="sm" onClick={() => respond.mutate({ id: p.id, accept: true })}>
                  {t("Join")}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => respond.mutate({ id: p.id, accept: false })}>
                  {t("Decline")}
                </Button>
              </div>
            )}
            {p.role === "OWNER" && (
              <>
                {p.members.map((m) => (
                  <div key={m.id} className="mt-2 flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">
                      {m.name} <span className="text-xs text-muted">· {t(m.status === "INVITED" ? "invited" : "member")}</span>
                    </span>
                    <Input
                      type="number"
                      inputMode="numeric"
                      defaultValue={m.monthly_limit ? Number(m.monthly_limit) : ""}
                      placeholder={t("No limit")}
                      onBlur={(e) => member.mutate({ id: p.id, member_id: m.id, monthly_limit: e.target.value ? Number(e.target.value) : null })}
                      className="!w-24 !py-1 text-xs"
                      aria-label={t("Monthly limit for {name}", { name: m.name })}
                    />
                    <button onClick={() => member.mutate({ id: p.id, member_id: m.id, remove: true })} className="p-1 text-muted hover:text-danger" aria-label={`${t("Remove")} ${m.name}`}>
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                ))}
                <div className="mt-2 flex gap-2">
                  <Input inputMode="tel" value={phones[p.id] ?? ""} onChange={(e) => setPhones((x) => ({ ...x, [p.id]: e.target.value }))} placeholder={t("Invite by mobile number")} className="!py-1.5 text-xs" />
                  <Button size="sm" variant="secondary" icon={<UserPlus className="size-3.5" />} disabled={(phones[p.id] ?? "").replace(/\D/g, "").length < 10} onClick={() => invite.mutate({ id: p.id, phone: phones[p.id] })}>
                    {t("Invite")}
                  </Button>
                </div>
                <button onClick={() => openFile(`/api/v1/rider/profiles/${p.id}/statement/?export=csv`)} className="mt-2 flex items-center gap-1 text-xs font-semibold text-brand-strong">
                  <Download className="size-3.5" /> {t("This month's statement (CSV)")}
                </button>
              </>
            )}
          </div>
        ))}
      </div>
      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t("New profile")}
        footer={
          <Button block loading={create.isPending} disabled={form.name.trim().length < 2} onClick={() => create.mutate()}>
            {t("Create")}
          </Button>
        }
      >
        <Segmented
          value={form.kind}
          onChange={(kind) => setForm((f) => ({ ...f, kind }))}
          options={[
            { value: "FAMILY", label: t("Family") },
            { value: "BUSINESS", label: t("Business") },
          ]}
        />
        <Field label={t("Name")} className="mt-3">
          <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder={form.kind === "BUSINESS" ? t("Acme Pvt Ltd") : t("Raman family")} />
        </Field>
        {form.kind === "BUSINESS" && (
          <Field label="GSTIN" className="mt-3">
            <Input value={form.gstin} maxLength={15} onChange={(e) => setForm((f) => ({ ...f, gstin: e.target.value.toUpperCase() }))} placeholder={t("Optional, for GST invoices")} />
          </Field>
        )}
        <p className="mt-3 text-xs text-muted">{t("Rides booked on this profile are paid from your wallet. You can set a monthly limit per member.")}</p>
      </Modal>
    </div>
  );
}
