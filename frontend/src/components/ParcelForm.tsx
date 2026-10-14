/** Parcel delivery: the sender's form, the delivery card on the trip, and the driver's code entry. */

import { clsx } from "clsx";
import { Package } from "lucide-react";

import { Field, Input, Select } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

export interface ParcelDetails {
  recipient_name: string;
  recipient_phone: string;
  category: string;
  weight_kg: number;
  instructions: string;
}

export const EMPTY_PARCEL: ParcelDetails = { recipient_name: "", recipient_phone: "", category: "DOCUMENTS", weight_kg: 1, instructions: "" };

const CATEGORIES = [
  ["DOCUMENTS", "Documents"],
  ["FOOD", "Food"],
  ["ELECTRONICS", "Electronics"],
  ["CLOTHES", "Clothes"],
  ["KEYS", "Keys"],
  ["OTHER", "Other"],
] as const;

export const parcelReady = (p: ParcelDetails) => p.recipient_name.trim().length >= 2 && p.recipient_phone.replace(/\D/g, "").length >= 10;

/** On the booking screen when sending a parcel. */
export function ParcelForm({ value, onChange }: { value: ParcelDetails; onChange: (p: ParcelDetails) => void }) {
  const set = (patch: Partial<ParcelDetails>) => onChange({ ...value, ...patch });
  return (
    <div className="mt-3 rounded-2xl border border-line p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Package className="size-4" /> {t("Parcel details")}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label={t("Recipient")}>
          <Input value={value.recipient_name} onChange={(e) => set({ recipient_name: e.target.value })} placeholder="Meena" />
        </Field>
        <Field label={t("Their mobile")}>
          <Input inputMode="tel" value={value.recipient_phone} onChange={(e) => set({ recipient_phone: e.target.value })} placeholder="98765 43210" />
        </Field>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {CATEGORIES.map(([code, label]) => (
          <button
            key={code}
            onClick={() => set({ category: code })}
            aria-pressed={value.category === code}
            className={clsx("rounded-full border px-3 py-1 text-xs font-semibold", value.category === code ? "border-fg bg-ink text-ink-fg" : "border-line text-muted")}
          >
            {t(label)}
          </button>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-[1fr_2fr] gap-2">
        <Field label={t("Weight")}>
          <Select value={value.weight_kg} onChange={(e) => set({ weight_kg: Number(e.target.value) })}>
            {[0.5, 1, 2, 3, 5, 8, 10].map((kg) => (
              <option key={kg} value={kg}>
                {t("up to {n} kg", { n: kg })}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("Note for the driver")}>
          <Input value={value.instructions} maxLength={200} onChange={(e) => set({ instructions: e.target.value })} placeholder={t("e.g. Fragile, call on arrival")} />
        </Field>
      </div>
      <p className="mt-2 text-[11px] text-muted">{t("No cash, jewellery, prescription medicines, alcohol or anything illegal. The recipient gets a tracking link and a code to give the driver.")}</p>
    </div>
  );
}

/** On the sender's trip screen: the code to pass on, and delivery status. */
export function ParcelCard({ trip }: { trip: Trip }) {
  const parcel = trip.parcel;
  if (!parcel) return null;
  return (
    <div className="mt-3 rounded-2xl bg-surface-2 px-4 py-3 text-sm">
      <div className="flex items-center gap-2 font-semibold">
        <Package className="size-4" /> {t("To {name}", { name: parcel.recipient_name })} · {t(parcel.category_label)} · {Number(parcel.weight_kg)} kg
      </div>
      {parcel.delivered_at ? (
        <p className="mt-1 text-xs text-brand-strong">{t("Delivered {when}", { when: dateTime(parcel.delivered_at) })}</p>
      ) : (
        parcel.delivery_code && (
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="text-xs text-muted">{t("Delivery code (we've sent it to {name} too)", { name: parcel.recipient_name })}</span>
            <span className="font-mono text-2xl font-bold tracking-[0.3em]">{parcel.delivery_code}</span>
          </div>
        )
      )}
    </div>
  );
}
