import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, ChevronRight, Copy, Gift, House, LifeBuoy, LogOut, MapPin, Moon, Share2, Shield, Sun, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { PushToggle } from "@/components/PushToggle";
import { Avatar, Button, Field, Input, Modal, Select, Stars } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import type { Place, Rider, SavedPlace } from "@/lib/types";

export function ThemeRow() {
  const [theme, setTheme] = useTheme();
  return (
    <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="flex w-full items-center gap-3 py-3.5 text-left">
      {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
      <span className="flex-1 font-medium">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}

export function LogoutRow() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  return (
    <button
      onClick={async () => {
        await logout();
        navigate("/login");
      }}
      className="flex w-full items-center gap-3 py-3.5 text-left text-danger"
    >
      <LogOut className="size-5" />
      <span className="font-medium">Log out</span>
    </button>
  );
}

export default function RiderAccount() {
  const qc = useQueryClient();
  const profile = useQuery({ queryKey: ["rider", "me"], queryFn: () => api.get<Rider>("rider/me/") });
  const places = useQuery({ queryKey: ["places", "saved"], queryFn: () => api.get<SavedPlace[]>("rider/places/") });
  const [emergency, setEmergency] = useState(false);
  const [placeOpen, setPlaceOpen] = useState(false);
  const [contact, setContact] = useState({ emergency_contact_name: "", emergency_contact_phone: "" });
  const [place, setPlace] = useState({ label: "HOME", query: "", picked: null as Place | null });

  const search = useQuery({
    queryKey: ["places", "search", place.query],
    queryFn: () => api.get<Place[]>(`places/?q=${encodeURIComponent(place.query)}`),
    enabled: place.query.length >= 2 && !place.picked,
  });

  const save = useMutation({
    mutationFn: () => api.patch<Rider>("rider/me/", contact),
    onSuccess: () => {
      toast.success("Emergency contact saved");
      setEmergency(false);
      qc.invalidateQueries({ queryKey: ["rider", "me"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });
  const addPlace = useMutation({
    mutationFn: () =>
      api.post("rider/places/", {
        label: place.label,
        name: place.picked!.name,
        address: place.picked!.address,
        lat: place.picked!.lat,
        lng: place.picked!.lng,
      }),
    onSuccess: () => {
      toast.success("Place saved");
      setPlaceOpen(false);
      setPlace({ label: "HOME", query: "", picked: null });
      qc.invalidateQueries({ queryKey: ["places", "saved"] });
    },
    onError: (err) => toast.error(err instanceof ApiError && err.code === "validation_error" ? "You already have a place with that label." : (err as Error).message),
  });
  const removePlace = useMutation({
    mutationFn: (id: number) => api.del(`rider/places/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["places", "saved"] }),
  });

  const rider = profile.data;
  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <div className="flex items-center gap-4">
        <Avatar name={rider?.name ?? "Rider"} size={64} />
        <div>
          <h1 className="text-xl font-bold">{rider?.name}</h1>
          <div className="mt-0.5 flex items-center gap-3 text-sm text-muted">
            <Stars value={rider?.rating ?? 5} /> · {rider?.completed_trips ?? 0} trips
          </div>
        </div>
      </div>

      {rider && <InviteCard rider={rider} />}

      <h2 className="mt-6 text-xs font-semibold tracking-wide text-muted uppercase">Saved places</h2>
      <div className="divide-y divide-line">
        {(places.data ?? []).map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-3">
            {p.label === "HOME" ? <House className="size-5" /> : p.label === "WORK" ? <Briefcase className="size-5" /> : <MapPin className="size-5" />}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold">{p.label === "OTHER" ? p.name : p.label === "HOME" ? "Home" : "Work"}</div>
              <div className="truncate text-xs text-muted">{p.name}</div>
            </div>
            <button onClick={() => removePlace.mutate(p.id)} className="p-1 text-muted hover:text-danger" aria-label="Remove place">
              <Trash2 className="size-4" />
            </button>
          </div>
        ))}
        <button onClick={() => setPlaceOpen(true)} className="w-full py-3 text-left text-sm font-semibold text-brand-strong">
          + Add a place
        </button>
      </div>

      <h2 className="mt-4 text-xs font-semibold tracking-wide text-muted uppercase">Safety & help</h2>
      <div className="divide-y divide-line">
        <PushToggle audience="rider" />
        <button
          onClick={() => {
            setContact({ emergency_contact_name: rider?.emergency_contact_name ?? "", emergency_contact_phone: rider?.emergency_contact_phone ?? "" });
            setEmergency(true);
          }}
          className="flex w-full items-center gap-3 py-3.5 text-left"
        >
          <Shield className="size-5" />
          <span className="flex-1">
            <span className="block font-medium">Emergency contact</span>
            <span className="block text-xs text-muted">{rider?.emergency_contact_name || "Not set"}</span>
          </span>
          <ChevronRight className="size-4 text-muted" />
        </button>
        <Link to="/ride/support" className="flex items-center gap-3 py-3.5">
          <LifeBuoy className="size-5" />
          <span className="flex-1 font-medium">Help & support tickets</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
        <ThemeRow />
        <LogoutRow />
      </div>

      <Modal
        open={emergency}
        onClose={() => setEmergency(false)}
        title="Emergency contact"
        footer={
          <Button onClick={() => save.mutate()} loading={save.isPending}>
            Save
          </Button>
        }
      >
        <p className="mb-3 text-sm text-muted">We'll share your trip with this person if you press SOS.</p>
        <Field label="Name">
          <Input value={contact.emergency_contact_name} onChange={(e) => setContact((c) => ({ ...c, emergency_contact_name: e.target.value }))} />
        </Field>
        <Field label="Phone" className="mt-3">
          <Input value={contact.emergency_contact_phone} onChange={(e) => setContact((c) => ({ ...c, emergency_contact_phone: e.target.value }))} />
        </Field>
      </Modal>

      <Modal
        open={placeOpen}
        onClose={() => setPlaceOpen(false)}
        title="Save a place"
        footer={
          <Button onClick={() => addPlace.mutate()} disabled={!place.picked} loading={addPlace.isPending}>
            Save place
          </Button>
        }
      >
        <Field label="Label">
          <Select value={place.label} onChange={(e) => setPlace((p) => ({ ...p, label: e.target.value }))}>
            <option value="HOME">Home</option>
            <option value="WORK">Work</option>
            <option value="OTHER">Other</option>
          </Select>
        </Field>
        <Field label="Search" className="mt-3">
          <Input value={place.picked?.name ?? place.query} onChange={(e) => setPlace((p) => ({ ...p, query: e.target.value, picked: null }))} placeholder="Landmark or area" />
        </Field>
        <div className="mt-2 space-y-1">
          {(search.data ?? []).map((result) => (
            <button key={`${result.name}-${result.lat}`} onClick={() => setPlace((p) => ({ ...p, picked: result }))} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2">
              <span className="font-medium">{result.name}</span> <span className="text-muted">· {result.address}</span>
            </button>
          ))}
        </div>
      </Modal>
    </div>
  );
}

/** "Invite friends, you both get ₹50": shares a sign-up link with the rider's code filled in. */
function InviteCard({ rider }: { rider: Rider }) {
  const bonus = Number(rider.referrals?.bonus ?? 50);
  const link = `${location.origin}/signup?ref=${rider.referral_code}`;
  async function share() {
    const text = `Ride with me on Ride Pulse! Sign up with my code ${rider.referral_code} and we both get ₹${bonus} after your first ride.`;
    try {
      if (navigator.share) {
        await navigator.share({ title: "Ride Pulse", text, url: link });
        return;
      }
    } catch {
      return; // the share sheet was dismissed
    }
    await navigator.clipboard?.writeText(`${text} ${link}`);
    toast.success("Invite link copied");
  }
  return (
    <div className="mt-5 rounded-2xl bg-brand-soft p-4">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand text-white">
          <Gift className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-brand-fg">Invite friends, you both get ₹{bonus}</div>
          <div className="text-xs text-brand-strong dark:text-brand-fg/80">Paid to both wallets after their first ride.</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={() => {
            navigator.clipboard?.writeText(rider.referral_code);
            toast.success("Referral code copied");
          }}
          className="flex flex-1 items-center justify-between rounded-xl border border-dashed border-brand/50 bg-surface px-3 py-2 font-mono text-sm font-bold"
          aria-label="Copy referral code"
        >
          {rider.referral_code}
          <Copy className="size-4 text-muted" />
        </button>
        <Button variant="brand" onClick={share} icon={<Share2 className="size-4" />}>
          Invite
        </Button>
      </div>
      {rider.referrals && rider.referrals.joined > 0 && (
        <div className="mt-3 text-xs text-brand-strong dark:text-brand-fg/80">
          {rider.referrals.joined} {rider.referrals.joined === 1 ? "friend" : "friends"} joined · ₹{Number(rider.referrals.earned)} earned
        </div>
      )}
    </div>
  );
}
