/**
 * "Where to?" suggestions. With Google Maps enabled they come from Google Places Autocomplete
 * (any address in India); otherwise, or if Google fails, from Ride Pulse's own landmark and
 * neighbourhood search.
 */

import { useQuery } from "@tanstack/react-query";
import { useMapsLibrary } from "@vis.gl/react-google-maps";
import { MapPin } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useMapProvider } from "@/components/map";
import { Badge, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { Place } from "@/lib/types";

export interface PickedPlace {
  lat: number;
  lng: number;
  name: string;
}

interface Suggestion {
  key: string;
  name: string;
  address: string;
  category: string;
  pick: () => Promise<PickedPlace>;
}

function SuggestionList({ items, loading, onPick, empty }: { items: Suggestion[]; loading: boolean; onPick: (p: PickedPlace) => void; empty: boolean }) {
  return (
    <>
      {loading && <Spinner className="mx-auto my-3" />}
      {items.map((s) => (
        <button key={s.key} onClick={async () => onPick(await s.pick())} className="flex w-full items-center gap-3 py-2.5 text-left">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-3">
            <MapPin className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{s.name}</span>
            <span className="block truncate text-xs text-muted">{s.address}</span>
          </span>
          {s.category && <Badge>{s.category}</Badge>}
        </button>
      ))}
      {empty && !loading && !items.length && <p className="py-6 text-center text-sm text-muted">No matches. Try a landmark like "Central", "Phoenix" or "Airport".</p>}
    </>
  );
}

function ApiSuggestions({ query, onPick }: { query: string; onPick: (p: PickedPlace) => void }) {
  const results = useQuery({
    queryKey: ["places", "search", query],
    queryFn: () => api.get<Place[]>(`places/?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length >= 2,
  });
  const items: Suggestion[] = (results.data ?? []).map((p) => ({
    key: `${p.name}-${p.lat}`,
    name: p.name,
    address: p.address,
    category: p.category,
    pick: async () => ({ lat: p.lat, lng: p.lng, name: p.name }),
  }));
  return <SuggestionList items={items} loading={results.isFetching} onPick={onPick} empty={query.length >= 2} />;
}

function GoogleSuggestions({ query, near, onPick }: { query: string; near: { lat: number; lng: number }; onPick: (p: PickedPlace) => void }) {
  const places = useMapsLibrary("places");
  const session = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!places || query.trim().length < 2) {
      setItems([]);
      return;
    }
    let cancelled = false;
    session.current ??= new places.AutocompleteSessionToken();
    setLoading(true);
    places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
      input: query,
      sessionToken: session.current,
      includedRegionCodes: ["in"],
      locationBias: { center: near, radius: 30_000 },
    })
      .then(({ suggestions }) => {
        if (cancelled) return;
        setItems(
          suggestions
            .map((s) => s.placePrediction)
            .filter((p): p is google.maps.places.PlacePrediction => !!p)
            .map((p) => ({
              key: p.placeId,
              name: p.mainText?.text ?? p.text.text,
              address: p.secondaryText?.text ?? "",
              category: "",
              pick: async () => {
                const place = p.toPlace();
                await place.fetchFields({ fields: ["location", "displayName"] });
                session.current = null; // a selection ends the billing session
                return { lat: place.location!.lat(), lng: place.location!.lng(), name: place.displayName ?? p.text.text };
              },
            })),
        );
      })
      .catch(() => !cancelled && setFailed(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [places, query, near.lat, near.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) return <ApiSuggestions query={query} onPick={onPick} />;
  return <SuggestionList items={items} loading={loading} onPick={onPick} empty={query.length >= 2} />;
}

export function PlaceSuggestions(props: { query: string; near: { lat: number; lng: number }; onPick: (p: PickedPlace) => void }) {
  const { provider } = useMapProvider();
  return provider === "google" ? <GoogleSuggestions {...props} /> : <ApiSuggestions query={props.query} onPick={props.onPick} />;
}

/** Name a dropped pin: Google reverse geocoding when available, otherwise the platform's API. */
export async function describePoint(lat: number, lng: number, provider: "google" | "osm"): Promise<string> {
  if (provider === "google" && typeof google !== "undefined" && google.maps?.Geocoder) {
    try {
      const { results } = await new google.maps.Geocoder().geocode({ location: { lat, lng } });
      const best = results.find((r) => !r.types.includes("plus_code")) ?? results[0];
      if (best) return best.formatted_address.split(",").slice(0, 2).join(",").trim();
    } catch {
      /* fall through to the platform API */
    }
  }
  const [place] = await api.get<Place[]>(`places/?lat=${lat}&lng=${lng}`);
  return place?.name ?? "Pinned location";
}
