/**
 * The phone as the driver's GPS: follows `watchPosition`, sends a fix when the car has moved
 * 15 m or every 4 s (whichever first, to save battery and data), and holds a screen wake lock
 * so the browser keeps tracking while the driver has the app open. A native app would also
 * track with the screen off; in a browser the screen has to stay on.
 */
import { useEffect, useRef, useState } from "react";

export type GpsFix = { lat: number; lng: number; heading: number | null; speedKmh: number | null; accuracy: number };
export type GpsState = "off" | "starting" | "tracking" | "denied" | "unavailable";

function metres(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const dy = (b.lat - a.lat) * 111_320;
  const dx = (b.lng - a.lng) * 111_320 * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dx, dy);
}

export function usePhoneGps(enabled: boolean, onFix: (fix: GpsFix) => void, { keepAwake = true }: { keepAwake?: boolean } = {}): GpsState {
  const [state, setState] = useState<GpsState>("off");
  const handler = useRef(onFix);
  handler.current = onFix;

  useEffect(() => {
    if (!enabled) {
      setState("off");
      return;
    }
    if (!("geolocation" in navigator)) {
      setState("unavailable");
      return;
    }
    setState("starting");
    let last: { lat: number; lng: number; at: number } | null = null;
    const watch = navigator.geolocation.watchPosition(
      ({ coords }) => {
        setState("tracking");
        const here = { lat: coords.latitude, lng: coords.longitude };
        const now = Date.now();
        if (last && metres(last, here) < 15 && now - last.at < 4000) return;
        last = { ...here, at: now };
        handler.current({
          ...here,
          heading: coords.heading ?? null,
          speedKmh: coords.speed != null ? coords.speed * 3.6 : null,
          accuracy: coords.accuracy,
        });
      },
      (err) => setState(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20_000 },
    );

    // Keep the screen on while tracking; browsers drop the lock when the tab is hidden.
    let lock: { release(): Promise<void> } | null = null;
    const wakeLock = (navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> } }).wakeLock;
    const acquire = () => {
      if (keepAwake && document.visibilityState === "visible") wakeLock?.request("screen").then((l) => (lock = l)).catch(() => undefined);
    };
    acquire();
    document.addEventListener("visibilitychange", acquire);

    return () => {
      navigator.geolocation.clearWatch(watch);
      document.removeEventListener("visibilitychange", acquire);
      lock?.release().catch(() => undefined);
    };
  }, [enabled, keepAwake]);

  return state;
}
