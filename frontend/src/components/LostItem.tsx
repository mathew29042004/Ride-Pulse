/** Lost and found: the rider reports an item left in the car; the driver answers found / not found. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageSearch } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { CallButton } from "@/components/CallButton";
import { Button, Modal, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";
import type { Trip } from "@/lib/types";

export interface LostItem {
  id: number;
  trip_id: number;
  trip_number: string;
  rider_name: string;
  description: string;
  status: "REPORTED" | "FOUND" | "NOT_FOUND" | "ON_THE_WAY" | "AT_HUB" | "RETURNED" | "DISPOSED";
  category?: string;
  return_trip_id?: number | null;
  status_label: string;
  driver_note: string;
  created_at: string;
}

const REPORT_DAYS = 7;
const CATEGORIES = [
  ["PHONE", "Phone"],
  ["WALLET", "Wallet or purse"],
  ["KEYS", "Keys"],
  ["DOCUMENTS", "Documents or ID"],
  ["BAG", "Bag"],
  ["ELECTRONICS", "Laptop or electronics"],
  ["CLOTHING", "Clothing"],
  ["OTHER", "Something else"],
] as const;
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** On a completed trip (rider side): report, then follow the driver's answer. */
export function LostItemCard({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const key = ["trips", String(trip.id), "lost-item"];
  const item = useQuery({ queryKey: key, queryFn: async () => (await api.get<LostItem | undefined>(`trips/${trip.id}/lost-item/`)) ?? null });
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("OTHER");
  const navigate = useNavigate();
  const deliver = useMutation({
    // To where the rider is now (or their pickup point if the phone gives no location).
    mutationFn: async () => {
      const here = await new Promise<{ lat: number; lng: number } | null>((resolve) =>
        "geolocation" in navigator ? navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }), () => resolve(null), { timeout: 5000 }) : resolve(null),
      );
      return api.post<{ trip_id: number }>(`trips/${trip.id}/lost-item/deliver/`, { ...(here ?? { lat: trip.pickup_lat, lng: trip.pickup_lng }), address: here ? "My location" : trip.pickup_address });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: key });
      toast.success("A courier will bring it to you.");
      navigate(`/ride/trips/${r.trip_id}`);
    },
    onError: (err) => toast.error(errorText(err, "Couldn't book the delivery.")),
  });
  const send = useMutation({
    mutationFn: () => api.post<LostItem>(`trips/${trip.id}/lost-item/`, { description, category }),
    onSuccess: (row) => {
      qc.setQueryData(key, row);
      setOpen(false);
      toast.success("We've told your driver. You'll hear back here.");
    },
    onError: (err) => toast.error(errorText(err, "Couldn't send the report.")),
  });
  const returned = useMutation({
    mutationFn: () => api.post<LostItem>(`trips/${trip.id}/lost-item/returned/`),
    onSuccess: (row) => qc.setQueryData(key, row),
    onError: (err) => toast.error(errorText(err, "Couldn't update.")),
  });

  const tooLate = trip.completed_at && Date.now() - new Date(trip.completed_at).getTime() > REPORT_DAYS * 86_400_000;
  const row = item.data;
  if (item.isLoading || (!row && tooLate)) return null;

  return (
    <>
      {row ? (
        <div className="mt-3 rounded-2xl bg-surface-2 px-4 py-3 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 font-semibold">
              <PackageSearch className="size-4" /> {row.description}
            </span>
            <StatusBadge status={row.status} label={row.status_label} />
          </div>
          {row.driver_note && <p className="mt-1 text-muted">Driver: “{row.driver_note}”</p>}
          {row.status === "REPORTED" && <p className="mt-1 text-xs text-muted">Waiting for your driver to check the car.</p>}
          {row.status === "NOT_FOUND" && <p className="mt-1 text-xs text-muted">Our support team will follow up on your ticket.</p>}
          {row.status === "FOUND" && (
            <>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <CallButton tripId={trip.id} name={trip.driver?.name ?? "your driver"} />
                <Button variant="secondary" loading={returned.isPending} onClick={() => returned.mutate()}>
                  I got it back
                </Button>
              </div>
              <Button className="mt-2 w-full" variant="outline" loading={deliver.isPending} onClick={() => deliver.mutate()}>
                Deliver it to me (bike parcel)
              </Button>
            </>
          )}
          {row.status === "ON_THE_WAY" && row.return_trip_id && (
            <Button className="mt-2 w-full" variant="outline" onClick={() => navigate(`/ride/trips/${row.return_trip_id}`)}>
              Track the delivery
            </Button>
          )}
          {row.status === "AT_HUB" && <p className="mt-1 text-xs text-muted">It's at our hub in your city. Collect it within 30 days with your ID, or ask support to deliver it.</p>}
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className="mt-3 flex w-full items-center gap-2 rounded-2xl bg-surface-2 px-4 py-3 text-left text-sm font-semibold">
          <PackageSearch className="size-4" /> {t("Lost something in the car?")}
        </button>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Report a lost item"
        footer={
          <Button className="w-full" loading={send.isPending} disabled={description.trim().length < 3} onClick={() => send.mutate()}>
            Tell my driver
          </Button>
        }
      >
        <p className="mb-2 text-sm text-muted">Describe it so your driver can find it. You can call each other through the app for 24 hours.</p>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="mb-2 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm" aria-label="What did you lose?">
          {CATEGORIES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <Textarea rows={3} maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Black backpack on the back seat" />
      </Modal>
    </>
  );
}

/** Driver side: open reports from riders, answered right from the home screen. */
export function DriverLostItems() {
  const qc = useQueryClient();
  const items = useQuery({ queryKey: ["driver", "lost-items"], queryFn: () => api.get<LostItem[]>("driver/lost-items/"), refetchInterval: 60_000 });
  const answer = useMutation({
    mutationFn: ({ item, path, body }: { item: LostItem; path: string; body?: object }) => api.post<LostItem>(`trips/${item.trip_id}/lost-item/${path}/`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["driver", "lost-items"] }),
    onError: (err) => toast.error(errorText(err, "Couldn't update.")),
  });
  if (!items.data?.length) return null;

  return (
    <div className="rp-overlay relative z-[600] mx-3 mb-2 space-y-2">
      {items.data.map((item) => (
        <div key={item.id} className="rounded-2xl bg-surface p-3 text-sm shadow-[var(--shadow-float)]">
          <div className="flex items-center gap-2 font-semibold">
            <PackageSearch className="size-4 text-amber-500" /> {item.rider_name} left “{item.description}”
          </div>
          <div className="mt-0.5 text-xs text-muted">{item.trip_number}</div>
          {item.status === "REPORTED" ? (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Button size="sm" loading={answer.isPending} onClick={() => answer.mutate({ item, path: "answer", body: { found: true } })}>
                Found it
              </Button>
              <Button size="sm" variant="secondary" loading={answer.isPending} onClick={() => answer.mutate({ item, path: "answer", body: { found: false } })}>
                Not in my car
              </Button>
            </div>
          ) : (
            <div className="mt-2 flex items-center gap-2">
              <CallButton tripId={item.trip_id} name={item.rider_name} compact />
              <Button size="sm" variant="secondary" className="flex-1" loading={answer.isPending} onClick={() => answer.mutate({ item, path: "returned" })}>
                Handed it back
              </Button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
