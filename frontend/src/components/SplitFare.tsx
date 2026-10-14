/** Split fare: the rider asks friends for a share; friends pay or decline from Activity. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Users, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Input, Modal, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { inr } from "@/lib/format";
import type { Paginated, Trip } from "@/lib/types";

export interface FareSplit {
  id: number;
  trip_id: number;
  trip_number: string;
  rider_name: string;
  friend_name: string;
  ride_type: string;
  dropoff_address: string;
  trip_fare: string;
  completed_at: string;
  amount: string;
  status: "REQUESTED" | "PAID" | "DECLINED" | "CANCELLED";
  status_label: string;
  /** Sent to me to pay (rather than a request I sent). */
  incoming: boolean;
}

/** On a finished, paid trip: ask friends to split, then see who has paid. */
export function SplitFareCard({ trip }: { trip: Trip }) {
  const qc = useQueryClient();
  const key = ["trips", String(trip.id), "split"];
  const splits = useQuery({ queryKey: key, queryFn: () => api.get<FareSplit[]>(`trips/${trip.id}/split/`), enabled: trip.payment_status === "PAID" });
  const [open, setOpen] = useState(false);
  const [phones, setPhones] = useState([""]);
  const send = useMutation({
    mutationFn: () => api.post<FareSplit[]>(`trips/${trip.id}/split/`, { phones: phones.filter((p) => p.trim()) }),
    onSuccess: (rows) => {
      qc.setQueryData(key, rows);
      setOpen(false);
      toast.success(`Asked ${rows.length} ${rows.length === 1 ? "friend" : "friends"} for ${inr(rows[0].amount)} each`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't split the fare."),
  });
  if (trip.payment_status !== "PAID") return null;
  const active = (splits.data ?? []).filter((s) => s.status !== "CANCELLED");
  const each = (Number(trip.fare_total) / (phones.filter((p) => p.trim()).length + 1 || 1)).toFixed(2);

  return (
    <>
      {active.length ? (
        <div className="mt-3 rounded-2xl bg-surface-2 px-4 py-3">
          <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Users className="size-4" /> Fare split
          </div>
          {active.map((s) => (
            <div key={s.id} className="flex items-center justify-between py-1 text-sm">
              <span>{s.friend_name}</span>
              <span className="flex items-center gap-2">
                {inr(s.amount)} <StatusBadge status={s.status === "PAID" ? "COMPLETED" : s.status === "DECLINED" ? "CANCELLED" : "REQUESTED"} label={s.status_label} />
              </span>
            </div>
          ))}
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl border border-line py-2.5 text-sm font-semibold">
          <Users className="size-4" /> Split fare with friends
        </button>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Split this fare"
        footer={
          <Button block onClick={() => send.mutate()} loading={send.isPending} disabled={!phones.some((p) => p.trim())}>
            Ask for {inr(each)} each
          </Button>
        }
      >
        <p className="mb-3 text-sm text-muted">Add friends' phone numbers (Ride Pulse riders). Everyone pays an equal share of {inr(trip.fare_total)}; it comes back to your wallet.</p>
        <div className="space-y-2">
          {phones.map((phone, i) => (
            <div key={i} className="flex gap-2">
              <Input inputMode="tel" value={phone} onChange={(e) => setPhones(phones.map((p, j) => (j === i ? e.target.value : p)))} placeholder="Friend's mobile number" />
              {phones.length > 1 && (
                <button onClick={() => setPhones(phones.filter((_, j) => j !== i))} className="rounded-full p-2 text-muted hover:bg-surface-3" aria-label="Remove">
                  <X className="size-4" />
                </button>
              )}
            </div>
          ))}
        </div>
        {phones.length < 3 && (
          <button onClick={() => setPhones([...phones, ""])} className="mt-2 flex items-center gap-1 text-sm font-semibold text-brand-strong">
            <Plus className="size-4" /> Add another friend
          </button>
        )}
      </Modal>
    </>
  );
}

/** In Activity: friends' requests to split a fare with me. */
export function SplitRequests() {
  const qc = useQueryClient();
  const requests = useQuery({
    queryKey: ["fare-splits", "incoming"],
    queryFn: () => api.get<Paginated<FareSplit>>("fare-splits/?status=REQUESTED"),
    refetchInterval: 30_000,
  });
  const [method, setMethod] = useState<"UPI" | "WALLET">("UPI");
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "pay" | "decline" }) =>
      api.post<FareSplit>(`fare-splits/${id}/${action}/`, action === "pay" ? { method, payer_reference: "me@upi" } : undefined),
    onSuccess: (split) => {
      toast.success(split.status === "PAID" ? `Paid ${inr(split.amount)} to ${split.rider_name}` : "Request declined");
      qc.invalidateQueries({ queryKey: ["fare-splits"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Something went wrong."),
  });
  // Only requests sent to me (the API also returns the ones I sent).
  const incoming = (requests.data?.results ?? []).filter((s) => s.incoming && s.status === "REQUESTED");
  if (!incoming.length) return null;
  return (
    <div className="mb-3 px-2">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Payment requests</h2>
      {incoming.map((s) => (
        <div key={s.id} className="mb-2 rounded-2xl border border-line p-3">
          <div className="text-sm">
            <b>{s.rider_name}</b> split a {s.ride_type} ride to {s.dropoff_address || "their destination"}
          </div>
          <div className="mt-0.5 text-xs text-muted">
            Your share {inr(s.amount)} of {inr(s.trip_fare)}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <select value={method} onChange={(e) => setMethod(e.target.value as "UPI" | "WALLET")} className="rounded-xl border border-line bg-surface px-2 py-1.5 text-sm" aria-label="Pay with">
              <option value="UPI">UPI</option>
              <option value="WALLET">Wallet</option>
            </select>
            <Button size="sm" className="flex-1" onClick={() => act.mutate({ id: s.id, action: "pay" })} loading={act.isPending && act.variables?.id === s.id && act.variables.action === "pay"}>
              Pay {inr(s.amount)}
            </Button>
            <Button size="sm" variant="outline" onClick={() => act.mutate({ id: s.id, action: "decline" })}>
              Decline
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
