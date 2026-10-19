import { clsx } from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, ChevronRight, Copy, Gift, Heart, House, Languages, LifeBuoy, Building2, LogOut, Mail, MapPin, Moon, Share2, Sun, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { TrustLinks } from "@/components/TrustLinks";
import { PushToggle } from "@/components/PushToggle";
import { EcoCard, FareLocks } from "@/components/GreenAndLock";
import { ProfilesSection } from "@/components/Profiles";
import { RidePassCard } from "@/components/RidePassCard";
import { GuardianSettings } from "@/components/Guardian";
import { SafetySettings } from "@/components/SafetyPlus";
import { Avatar, Button, Field, Input, Modal, Select, Stars } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PREFERENCES } from "@/lib/preferences";
import { AccessibilitySettings, BusinessLinks, TeenAccounts } from "@/components/RiderExtras";
import { useTheme } from "@/lib/theme";
import { LANGUAGES, t, useLanguage } from "@/lib/i18n";
import type { Place, Rider, SavedPlace } from "@/lib/types";

export function ThemeRow() {
  const [theme, setTheme] = useTheme();
  return (
    <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="flex w-full items-center gap-3 py-3.5 text-left">
      {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
      <span className="flex-1 font-medium">{(theme === "dark" ? t("Light mode") : t("Dark mode"))}</span>
    </button>
  );
}

/** English, Tamil or Hindi for the rider and driver apps (remembered on this device). */
export function LanguageRow() {
  const [language, setLanguage] = useLanguage();
  return (
    <div className="flex items-center gap-3 py-3.5">
      <Languages className="size-5" />
      <span className="flex-1 font-medium">{t("Language")}</span>
      <div className="flex gap-1" role="radiogroup" aria-label={t("Language")}>
        {LANGUAGES.map(({ code, label }) => (
          <button
            key={code}
            role="radio"
            aria-checked={language === code}
            onClick={() => {
              void setLanguage(code);
              // So chat messages reach this person in their language (Language Bridge).
              api.patch("auth/me/", { language: code }).catch(() => undefined);
            }}
            className={clsx("rounded-full px-3 py-1 text-xs font-semibold", language === code ? "bg-ink text-ink-fg" : "bg-surface-3 text-muted")}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
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
      <span className="font-medium">{t("Log out")}</span>
    </button>
  );
}

export default function RiderAccount() {
  const qc = useQueryClient();
  const profile = useQuery({ queryKey: ["rider", "me"], queryFn: () => api.get<Rider>("rider/me/") });
  const places = useQuery({ queryKey: ["places", "saved"], queryFn: () => api.get<SavedPlace[]>("rider/places/") });
  const [placeOpen, setPlaceOpen] = useState(false);
  const [place, setPlace] = useState({ label: "HOME", query: "", picked: null as Place | null });

  const search = useQuery({
    queryKey: ["places", "search", place.query],
    queryFn: () => api.get<Place[]>(`places/?q=${encodeURIComponent(place.query)}`),
    enabled: place.query.length >= 2 && !place.picked,
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
      toast.success(t("Place saved"));
      setPlaceOpen(false);
      setPlace({ label: "HOME", query: "", picked: null });
      qc.invalidateQueries({ queryKey: ["places", "saved"] });
    },
    onError: (err) => toast.error(err instanceof ApiError && err.code === "validation_error" ? t("You already have a place with that label.") : (err as Error).message),
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
            <Stars value={rider?.rating ?? 5} /> · {t("{n} trips", { n: rider?.completed_trips ?? 0 })}
          </div>
        </div>
      </div>

      <RidePassCard />
      <EcoCard />
      <FareLocks />
      <ProfilesSection />
      <BusinessLinks />
      <TeenAccounts />
      {rider && <InviteCard rider={rider} />}
      <InvoiceEmailRow />

      {rider && <PreferencesAndFavourites rider={rider} />}
      {rider && <AccessibilitySettings rider={rider} />}

      <h2 className="mt-6 text-xs font-semibold tracking-wide text-muted uppercase">{t("Saved places")}</h2>
      <div className="divide-y divide-line">
        {(places.data ?? []).map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-3">
            {p.label === "HOME" ? <House className="size-5" /> : p.label === "WORK" ? <Briefcase className="size-5" /> : <MapPin className="size-5" />}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold">{p.label === "OTHER" ? p.name : p.label === "HOME" ? t("Home") : t("Work")}</div>
              <div className="truncate text-xs text-muted">{p.name}</div>
            </div>
            <button onClick={() => removePlace.mutate(p.id)} className="p-1 text-muted hover:text-danger" aria-label={t("Remove place")}>
              <Trash2 className="size-4" />
            </button>
          </div>
        ))}
        <button onClick={() => setPlaceOpen(true)} className="w-full py-3 text-left text-sm font-semibold text-brand-strong">
          + Add a place
        </button>
      </div>

      <h2 className="mt-4 text-xs font-semibold tracking-wide text-muted uppercase">{t("Safety & help")}</h2>
      <div className="divide-y divide-line">
        <PushToggle audience="rider" />
        <SafetySettings rider={rider} />
        <GuardianSettings />
        <TrustLinks base="/ride" />
        <Link to="/ride/commute" className="flex items-center gap-3 py-3.5">
          <Building2 className="size-5" />
          <span className="flex-1 font-medium">{t("Office commute")}</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
        <Link to="/ride/support" className="flex items-center gap-3 py-3.5">
          <LifeBuoy className="size-5" />
          <span className="flex-1 font-medium">{t("Help & support tickets")}</span>
          <ChevronRight className="size-4 text-muted" />
        </Link>
        <LanguageRow />
        <ThemeRow />
        <LogoutRow />
      </div>

      <Modal
        open={placeOpen}
        onClose={() => setPlaceOpen(false)}
        title={t("Save a place")}
        footer={
          <Button onClick={() => addPlace.mutate()} disabled={!place.picked} loading={addPlace.isPending}>
            {t("Save place")}
          </Button>
        }
      >
        <Field label={t("Label")}>
          <Select value={place.label} onChange={(e) => setPlace((p) => ({ ...p, label: e.target.value }))}>
            <option value="HOME">{t("Home")}</option>
            <option value="WORK">{t("Work")}</option>
            <option value="OTHER">{t("Other")}</option>
          </Select>
        </Field>
        <Field label={t("Search")} className="mt-3">
          <Input value={place.picked?.name ?? place.query} onChange={(e) => setPlace((p) => ({ ...p, query: e.target.value, picked: null }))} placeholder={t("Landmark or area")} />
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
    const text = t("Ride with me on Ride Pulse! Sign up with my code {code} and we both get ₹{bonus} after your first ride.", { code: rider.referral_code, bonus });
    try {
      if (navigator.share) {
        await navigator.share({ title: "Ride Pulse", text, url: link });
        return;
      }
    } catch {
      return; // the share sheet was dismissed
    }
    await navigator.clipboard?.writeText(`${text} ${link}`);
    toast.success(t("Invite link copied"));
  }
  return (
    <div className="mt-5 rounded-2xl bg-brand-soft p-4">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand text-white">
          <Gift className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-brand-fg">{t("Invite friends, you both get ₹{bonus}", { bonus })}</div>
          <div className="text-xs text-brand-strong dark:text-brand-fg/80">{t("Paid to both wallets after their first ride.")}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={() => {
            navigator.clipboard?.writeText(rider.referral_code);
            toast.success(t("Referral code copied"));
          }}
          className="flex flex-1 items-center justify-between rounded-xl border border-dashed border-brand/50 bg-surface px-3 py-2 font-mono text-sm font-bold"
          aria-label={t("Copy referral code")}
        >
          {rider.referral_code}
          <Copy className="size-4 text-muted" />
        </button>
        <Button variant="brand" onClick={share} icon={<Share2 className="size-4" />}>
          {t("Invite")}
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

/** Where ride invoices go. Riders who signed up by phone add an email here. */
function InvoiceEmailRow() {
  const { user, refreshUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const missing = !user?.email || user.email.endsWith(".invalid");
  const save = useMutation({
    mutationFn: () => api.patch("/api/v1/auth/me/", { email }),
    onSuccess: async () => {
      await refreshUser();
      setOpen(false);
      toast.success(t("Invoices will be emailed to ") + email.toLowerCase());
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Couldn't save the email.")),
  });
  return (
    <>
      <button
        onClick={() => {
          setEmail(missing ? "" : (user?.email ?? ""));
          setOpen(true);
        }}
        className="mt-3 flex w-full items-center gap-3 rounded-2xl border border-line px-4 py-3 text-left"
      >
        <Mail className="size-5 shrink-0 text-muted" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{missing ? t("Add an email for ride invoices") : t("Ride invoices")}</span>
          <span className="block truncate text-xs text-muted">{missing ? t("We'll email a GST invoice after every ride") : t("Sent to {email}", { email: user?.email ?? "" })}</span>
        </span>
        <ChevronRight className="size-4 text-muted" />
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("Invoice email")}
        footer={
          <Button block onClick={() => save.mutate()} loading={save.isPending} disabled={!email.includes("@")}>
            {t("Save")}
          </Button>
        }
      >
        <Field label={t("Email address")}>
          <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </Field>
        <p className="mt-2 text-xs text-muted">{t("Invoices and receipts are sent here after each paid ride.")}</p>
      </Modal>
    </>
  );
}

/** Default ride preferences (pre-selected when booking) and favourite drivers. */
function PreferencesAndFavourites({ rider }: { rider: Rider }) {
  const qc = useQueryClient();
  const defaults = rider.default_preferences ?? [];
  const save = useMutation({
    mutationFn: (values: string[]) => api.patch("rider/me/", { default_preferences: values }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rider", "me"] }),
    onError: () => toast.error(t("Couldn't save your preferences.")),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`rider/favourites/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rider", "me"] }),
  });
  return (
    <>
      <h2 className="mt-6 text-xs font-semibold tracking-wide text-muted uppercase">{t("Ride preferences")}</h2>
      <p className="mb-2 text-xs text-muted">{t("Selected for you every time you book. You can still change them per ride.")}</p>
      <div className="flex flex-wrap gap-1.5">
        {PREFERENCES.map(({ value, label, icon: Icon }) => {
          const on = defaults.includes(value);
          return (
            <button
              key={value}
              onClick={() => save.mutate(on ? defaults.filter((v) => v !== value) : [...defaults, value])}
              aria-pressed={on}
              className={on ? "flex items-center gap-1.5 rounded-full border border-fg bg-ink px-3 py-1.5 text-xs font-semibold text-ink-fg" : "flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-muted"}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          );
        })}
      </div>

      <h2 className="mt-6 text-xs font-semibold tracking-wide text-muted uppercase">{t("Favourite drivers")}</h2>
      {(rider.favourites ?? []).length === 0 ? (
        <p className="mt-1 text-xs text-muted">{t("Tap the heart after a ride to save a driver. Favourites nearby are asked first.")}</p>
      ) : (
        <div className="divide-y divide-line">
          {rider.favourites!.map((f) => (
            <div key={f.id} className="flex items-center gap-3 py-3">
              <Avatar name={f.name} size={36} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{f.name}</div>
                <div className="truncate text-xs text-muted">
                  ★ {Number(f.rating).toFixed(2)} · {f.vehicle}
                </div>
              </div>
              <button onClick={() => remove.mutate(f.id)} className="rounded-full p-2 text-muted hover:bg-surface-3" aria-label={`Remove ${f.name} from favourites`}>
                <Heart className="size-4 fill-rose-500 text-rose-500" />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
