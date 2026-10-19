import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CheckCircle2, Circle, Clock, FileText, Upload, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { RideTypeArt } from "@/components/RideTypeArt";
import { Badge, Button, Field, Input, Modal, Select, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date } from "@/lib/format";
import { useDriverMe } from "@/lib/hooks";
import type { DriverDocument, RideType } from "@/lib/types";
import { t } from "@/lib/i18n";

const DOCS = [
  { type: "DRIVING_LICENSE", label: "Driving licence", required: true },
  { type: "VEHICLE_RC", label: "Vehicle registration (RC)", required: true },
  { type: "VEHICLE_INSURANCE", label: "Vehicle insurance", required: true },
  { type: "POLICE_VERIFICATION", label: "Police verification", required: true },
  { type: "PAN", label: "PAN card", required: false },
];

const STEPS = ["PENDING_DOCUMENTS", "UNDER_REVIEW", "APPROVED"];

export default function DriverDocuments() {
  const qc = useQueryClient();
  const me = useDriverMe(10_000);
  const docs = useQuery({ queryKey: ["driver", "documents"], queryFn: () => api.get<DriverDocument[]>("driver/documents/") });
  const rideTypes = useQuery({ queryKey: ["ride-types"], queryFn: () => api.get<RideType[]>("ride-types/") });
  const [uploading, setUploading] = useState<string | null>(null);
  const [form, setForm] = useState({ number_last4: "", expires_on: "", file: null as File | null });
  const [vehicleOpen, setVehicleOpen] = useState(false);
  const [vehicle, setVehicle] = useState({ ride_type: "MINI", make: "", model: "", registration_number: "", year: "2022", color: "", seats: "4" });

  const upload = useMutation({
    mutationFn: () => {
      const data = new FormData();
      data.append("doc_type", uploading!);
      data.append("number_last4", form.number_last4);
      if (form.expires_on) data.append("expires_on", form.expires_on);
      if (form.file) data.append("file", form.file);
      return api.post<DriverDocument[]>("driver/documents/", data);
    },
    onSuccess: () => {
      toast.success(t("Document uploaded for review"));
      setUploading(null);
      setForm({ number_last4: "", expires_on: "", file: null });
      qc.invalidateQueries({ queryKey: ["driver"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Upload failed")),
  });
  const addVehicle = useMutation({
    mutationFn: () => api.post("driver/vehicle/", { ...vehicle, year: Number(vehicle.year), seats: Number(vehicle.seats) }),
    onSuccess: () => {
      toast.success(t("Vehicle registered"));
      setVehicleOpen(false);
      qc.invalidateQueries({ queryKey: ["driver"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't save the vehicle")),
  });

  const driver = me.data;
  const byType = new Map((docs.data ?? []).map((d) => [d.doc_type, d]));
  const step = STEPS.indexOf(driver?.onboarding_status ?? "");

  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <h1 className="text-2xl font-bold tracking-tight">{t("Documents")}</h1>
      <p className="text-sm text-muted">{t("Everything we need to keep riders safe.")}</p>

      {driver && (
        <div className="mt-4 rounded-2xl border border-line p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold">{t("Onboarding")}</span>
            <StatusBadge status={driver.onboarding_status} />
          </div>
          {driver.onboarding_status !== "SUSPENDED" && (
            <div className="mt-3 flex items-center gap-1">
              {["Documents", "Review", "Approved"].map((label, i) => (
                <div key={label} className="flex-1">
                  <div className={clsx("h-1.5 rounded-full", i <= step ? "bg-brand" : "bg-surface-3")} />
                  <div className={clsx("mt-1 text-[11px]", i <= step ? "font-semibold" : "text-muted")}>{label}</div>
                </div>
              ))}
            </div>
          )}
          {driver.suspended_reason && <p className="mt-2 text-sm text-danger">{driver.suspended_reason}</p>}
        </div>
      )}

      <h2 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Vehicle")}</h2>
      {driver?.vehicle ? (
        <div className="flex items-center gap-3 rounded-2xl bg-surface-2 p-4">
          <RideTypeArt code={driver.vehicle.ride_type} className="h-10 w-18" />
          <div className="flex-1">
            <div className="font-semibold">
              {driver.vehicle.make} {driver.vehicle.model}
            </div>
            <div className="text-xs text-muted">
              {driver.vehicle.color} · {driver.vehicle.year} · {driver.vehicle.ride_type}
            </div>
            <div className="mt-1 inline-block rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-xs font-bold">{driver.vehicle.registration_display}</div>
          </div>
        </div>
      ) : (
        <Button variant="outline" block onClick={() => setVehicleOpen(true)}>
          {t("Register your vehicle")}
        </Button>
      )}

      <h2 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t("Documents")}</h2>
      <div className="divide-y divide-line rounded-2xl border border-line">
        {DOCS.map(({ type, label, required }) => {
          const doc = byType.get(type);
          const Icon = !doc ? Circle : doc.status === "APPROVED" ? CheckCircle2 : doc.status === "PENDING" ? Clock : XCircle;
          return (
            <div key={type} className="flex items-center gap-3 px-4 py-3">
              <Icon className={clsx("size-5 shrink-0", !doc ? "text-line" : doc.status === "APPROVED" ? "text-brand" : doc.status === "PENDING" ? "text-amber-500" : "text-danger")} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">
                  {label} {!required && <Badge>optional</Badge>}
                </div>
                <div className="truncate text-xs text-muted">
                  {!doc && "Not uploaded"}
                  {doc && doc.status === "REJECTED" && `Rejected: ${doc.rejection_reason}`}
                  {doc && doc.status !== "REJECTED" && `${doc.status.toLowerCase()}${doc.expires_on ? ` · expires ${date(doc.expires_on)}` : ""}`}
                </div>
              </div>
              {(!doc || doc.status !== "PENDING") && (
                <Button size="sm" variant={doc?.status === "APPROVED" ? "ghost" : "secondary"} icon={<Upload className="size-3.5" />} onClick={() => setUploading(type)}>
                  {doc ? t("Replace") : t("Upload")}
                </Button>
              )}
            </div>
          );
        })}
      </div>

      <Modal
        open={!!uploading}
        onClose={() => setUploading(null)}
        title={t("Upload {document}", { document: t(DOCS.find((d) => d.type === uploading)?.label ?? "document") })}
        footer={
          <Button onClick={() => upload.mutate()} loading={upload.isPending}>
            {t("Submit for review")}
          </Button>
        }
      >
        <Field label={t("Last 4 characters of the document number")} hint="We only store the last 4 characters.">
          <Input maxLength={4} value={form.number_last4} onChange={(e) => setForm((f) => ({ ...f, number_last4: e.target.value.toUpperCase() }))} />
        </Field>
        <Field label={t("Expiry date")} className="mt-3">
          <Input type="date" value={form.expires_on} onChange={(e) => setForm((f) => ({ ...f, expires_on: e.target.value }))} />
        </Field>
        <Field label={t("Photo or PDF")} className="mt-3">
          <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-line px-4 py-4 text-sm text-muted hover:bg-surface-2">
            <FileText className="size-5" />
            {form.file ? form.file.name : t("Choose a file")}
            <input type="file" accept="image/*,application/pdf" className="hidden" onChange={(e) => setForm((f) => ({ ...f, file: e.target.files?.[0] ?? null }))} />
          </label>
        </Field>
      </Modal>

      <Modal
        open={vehicleOpen}
        onClose={() => setVehicleOpen(false)}
        title={t("Register your vehicle")}
        footer={
          <Button onClick={() => addVehicle.mutate()} loading={addVehicle.isPending}>
            {t("Save vehicle")}
          </Button>
        }
      >
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("Ride type")} className="col-span-2">
            <Select value={vehicle.ride_type} onChange={(e) => setVehicle((v) => ({ ...v, ride_type: e.target.value }))}>
              {(rideTypes.data ?? []).map((rt) => (
                <option key={rt.code} value={rt.code}>
                  {rt.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("Make")}>
            <Input value={vehicle.make} onChange={(e) => setVehicle((v) => ({ ...v, make: e.target.value }))} placeholder={t("Maruti Suzuki")} />
          </Field>
          <Field label={t("Model")}>
            <Input value={vehicle.model} onChange={(e) => setVehicle((v) => ({ ...v, model: e.target.value }))} placeholder={t("Swift")} />
          </Field>
          <Field label={t("Registration")} className="col-span-2">
            <Input value={vehicle.registration_number} onChange={(e) => setVehicle((v) => ({ ...v, registration_number: e.target.value.toUpperCase() }))} placeholder={t("TN 09 AB 1234")} />
          </Field>
          <Field label={t("Year")}>
            <Input type="number" value={vehicle.year} onChange={(e) => setVehicle((v) => ({ ...v, year: e.target.value }))} />
          </Field>
          <Field label={t("Colour")}>
            <Input value={vehicle.color} onChange={(e) => setVehicle((v) => ({ ...v, color: e.target.value }))} placeholder={t("White")} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
