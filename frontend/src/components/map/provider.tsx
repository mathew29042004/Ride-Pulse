import { APIProvider } from "@vis.gl/react-google-maps";
import { useQuery } from "@tanstack/react-query";
import { Component, createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";

export interface ClientConfig {
  company_name: string;
  currency_symbol: string;
  maps: { provider: "google" | "osm"; browser_key: string; map_id: string; routes: "google" | "estimate" };
  payments?: { razorpay_key_id: string };
  push?: { vapid_public_key: string };
}

export const configQuery = {
  queryKey: ["client-config"],
  queryFn: () => api.get<ClientConfig>("/api/config/"),
  staleTime: Number.POSITIVE_INFINITY,
};

interface MapsContextValue {
  provider: "google" | "osm";
  mapId: string;
  /** Switch the whole app to OpenStreetMap (bad key, billing disabled, script failure). */
  fail: (reason: string) => void;
}

const MapsContext = createContext<MapsContextValue>({ provider: "osm", mapId: "", fail: () => undefined });

export function useMapProvider(): MapsContextValue {
  return useContext(MapsContext);
}

declare global {
  interface Window {
    gm_authFailure?: () => void;
  }
}

/**
 * Chooses the map renderer for the whole app. With a Google Maps browser key from the server,
 * the Google Maps JavaScript API (and Places, for search) is loaded once here; otherwise the
 * apps use OpenStreetMap tiles through Leaflet and the platform's own place search.
 *
 * If Google rejects the key at runtime, the app fails over to OpenStreetMap instead of breaking.
 */
export function MapsProvider({ children }: { children: ReactNode }) {
  const config = useQuery(configQuery);
  const [failed, setFailed] = useState(false);
  const fail = useCallback((reason: string) => {
    console.warn(`Google Maps unavailable (${reason}); using OpenStreetMap instead.`);
    setFailed(true);
  }, []);
  useEffect(() => {
    // Google calls this global when the API key is invalid or not authorised for this site.
    window.gm_authFailure = () => fail("authentication failed");
    return () => {
      delete window.gm_authFailure;
    };
  }, [fail]);

  const maps = config.data?.maps;
  const google = !failed && maps?.provider === "google" && !!maps.browser_key;
  const value = useMemo<MapsContextValue>(
    () => ({ provider: google ? "google" : "osm", mapId: maps?.map_id || "DEMO_MAP_ID", fail }),
    [google, maps?.map_id, fail],
  );
  if (maps?.provider === "google" && maps.browser_key) {
    return (
      <APIProvider
        apiKey={maps.browser_key}
        region="IN"
        language="en"
        libraries={["places", "geocoding", "marker"]}
        onError={() => fail("the script failed to load")}
      >
        <MapsContext.Provider value={value}>{children}</MapsContext.Provider>
      </APIProvider>
    );
  }
  return <MapsContext.Provider value={value}>{children}</MapsContext.Provider>;
}

/** Catches errors thrown by Google map components and triggers the OpenStreetMap failover. */
export class GoogleMapBoundary extends Component<{ onFail: (reason: string) => void; children: ReactNode }, { broken: boolean }> {
  state = { broken: false };

  static getDerivedStateFromError() {
    return { broken: true };
  }

  componentDidCatch(error: Error) {
    this.props.onFail(error.message);
  }

  render() {
    return this.state.broken ? null : this.props.children;
  }
}
