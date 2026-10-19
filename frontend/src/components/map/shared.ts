/** Map pieces shared by the OpenStreetMap (Leaflet) and Google Maps renderers. */

import { useEffect, useRef } from "react";

export type LatLng = [number, number];

export const RIDE_TYPE_COLORS: Record<string, string> = {
  BIKE: "#8b5cf6",
  AUTO: "#eab308",
  MINI: "#6366f1",
  SEDAN: "#0f172a",
  SUV: "#2563eb",
};

export function carColor(rideType: string | null | undefined): string {
  return RIDE_TYPE_COLORS[rideType ?? ""] ?? "#6366f1";
}

/** Top-down car, drawn inline so markers need no image assets. */
export function carSvg(color: string): string {
  return `<svg viewBox="0 0 32 32" width="30" height="30">
    <ellipse cx="16" cy="17" rx="9" ry="13" fill="rgba(15,23,42,0.25)"/>
    <rect x="8" y="3" width="16" height="26" rx="6" fill="${color}" stroke="white" stroke-width="1.6"/>
    <rect x="10.5" y="8" width="11" height="5" rx="1.6" fill="rgba(255,255,255,0.85)"/>
    <rect x="10.5" y="20" width="11" height="4" rx="1.4" fill="rgba(255,255,255,0.6)"/>
  </svg>`;
}

/** A car icon; its heading is set (and smoothly turned) afterwards with `rotateCar`. */
export function carHtml(rideType: string | null | undefined, dim: boolean): string {
  return `<div class="rp-car" style="opacity: ${dim ? 0.55 : 1}">${carSvg(carColor(rideType))}</div>`;
}

/** Turn a car icon to `heading`, the short way round (350° to 10° turns 20°, not 340°). */
export function rotateCar(root: HTMLElement | null | undefined, heading: number) {
  const car = root?.querySelector<HTMLElement>(".rp-car");
  if (!car) return;
  const previous = Number(car.dataset.angle ?? heading);
  const delta = ((((heading - previous) % 360) + 540) % 360) - 180;
  const angle = previous + delta;
  car.dataset.angle = String(angle);
  car.style.transform = `rotate(${angle}deg)`;
}

export function bearing(from: LatLng, to: LatLng): number {
  const rad = Math.PI / 180;
  const [lat1, lat2] = [from[0] * rad, to[0] * rad];
  const dLng = (to[1] - from[1]) * rad;
  const y = Math.sin(dLng) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return ((Math.atan2(y, x) / rad) + 360) % 360;
}

function metresBetween(a: LatLng, b: LatLng): number {
  const dy = (b[0] - a[0]) * 111_320;
  const dx = (b[1] - a[1]) * 111_320 * Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot(dx, dy);
}

/**
 * Glide a marker between position updates, so cars drive instead of teleporting. Each move lasts
 * as long as the gap since the previous update, so a car streaming GPS every two seconds moves
 * continuously, always one update behind (as ride-hailing apps do). Positions are applied
 * imperatively, so a map full of cars doesn't re-render React sixty times a second.
 */
export function useGlide(lat: number, lng: number, apply: (position: LatLng) => void) {
  const state = useRef<{ at: LatLng; updatedAt: number; frame: number } | null>(null);
  const applyRef = useRef(apply);
  applyRef.current = apply;

  useEffect(() => {
    const target: LatLng = [lat, lng];
    const now = performance.now();
    const s = state.current;
    if (!s) {
      state.current = { at: target, updatedAt: now, frame: 0 };
      applyRef.current(target);
      return;
    }
    cancelAnimationFrame(s.frame);
    const from = s.at;
    const gap = now - s.updatedAt;
    s.updatedAt = now;
    // Teleport for big jumps (a new trip, a tap-to-move) and in hidden tabs (no frames run there).
    if (metresBetween(from, target) > 1500 || document.hidden) {
      s.at = target;
      applyRef.current(target);
      return;
    }
    const duration = gap > 8000 ? 1000 : Math.max(300, gap);
    const step = (time: number) => {
      const k = Math.min(1, Math.max(0, (time - now) / duration));
      s.at = [from[0] + (target[0] - from[0]) * k, from[1] + (target[1] - from[1]) * k];
      applyRef.current(s.at);
      if (k < 1) s.frame = requestAnimationFrame(step);
    };
    s.frame = requestAnimationFrame(step);
  }, [lat, lng]);

  useEffect(() => () => cancelAnimationFrame(state.current?.frame ?? 0), []);
}

/**
 * The direction a car faces: its reported heading, else the direction it last moved in.
 * Small jitters (under ~3 m) keep the previous heading so parked cars don't spin.
 */
export function useHeading(lat: number, lng: number, reported: number | null | undefined): number {
  const last = useRef<{ at: LatLng; heading: number } | null>(null);
  const here: LatLng = [lat, lng];
  if (reported !== null && reported !== undefined) {
    last.current = { at: here, heading: reported };
  } else if (!last.current) {
    last.current = { at: here, heading: 0 };
  } else if (metresBetween(last.current.at, here) > 3) {
    last.current = { at: here, heading: bearing(last.current.at, here) };
  }
  return last.current.heading;
}

/** Where `point` falls on `path`: the nearest point on it, how far off it is, and what's left. */
export function snapToPath(path: LatLng[], point: LatLng): { at: LatLng; offMetres: number; index: number; remainingKm: number } | null {
  if (path.length < 2) return null;
  const k = Math.cos((point[0] * Math.PI) / 180);
  let best = { dist2: Infinity, index: 0, t: 0 };
  for (let i = 0; i < path.length - 1; i++) {
    const [ay, ax] = path[i];
    const [by, bx] = path[i + 1];
    const dx = (bx - ax) * k;
    const dy = by - ay;
    const px = (point[1] - ax) * k;
    const py = point[0] - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, (px * dx + py * dy) / len2));
    const dist2 = (px - t * dx) ** 2 + (py - t * dy) ** 2;
    if (dist2 < best.dist2) best = { dist2, index: i, t };
  }
  const [ay, ax] = path[best.index];
  const [by, bx] = path[best.index + 1];
  const at: LatLng = [ay + (by - ay) * best.t, ax + (bx - ax) * best.t];
  let remaining = metresBetween(at, path[best.index + 1]);
  for (let i = best.index + 1; i < path.length - 1; i++) remaining += metresBetween(path[i], path[i + 1]);
  return { at, offMetres: metresBetween(at, point), index: best.index, remainingKm: remaining / 1000 };
}

export const PIN_HTML = {
  pickup: `<div style="width:22px;height:22px;border-radius:999px;background:#6366f1;border:4px solid white;box-shadow:0 2px 8px rgba(0,0,0,.35)"></div>`,
  dropoff: `<div style="width:20px;height:20px;background:#0b0f19;border:4px solid white;box-shadow:0 2px 8px rgba(0,0,0,.35)"></div>`,
  me: `<div style="position:relative;width:18px;height:18px">
      <div style="position:absolute;inset:-10px;border-radius:999px;background:rgba(14,165,233,.25);animation:pulse-ring 1.8s infinite"></div>
      <div style="position:absolute;inset:0;border-radius:999px;background:#0ea5e9;border:3px solid white;box-shadow:0 1px 6px rgba(0,0,0,.35)"></div>
    </div>`,
  stop: `<div style="width:16px;height:16px;border-radius:999px;background:#64748b;border:4px solid white;box-shadow:0 2px 8px rgba(0,0,0,.35)"></div>`,
  // Radar rings around the pickup while the app looks for a driver.
  searching: `<div style="position:relative;width:22px;height:22px">
      <div style="position:absolute;inset:-34px;border-radius:999px;background:rgba(16,185,129,.22);animation:radar 2.4s ease-out infinite"></div>
      <div style="position:absolute;inset:-34px;border-radius:999px;background:rgba(16,185,129,.22);animation:radar 2.4s ease-out 1.2s infinite"></div>
      <div style="position:absolute;inset:0;border-radius:999px;background:#6366f1;border:4px solid white;box-shadow:0 2px 8px rgba(0,0,0,.35)"></div>
    </div>`,
} as const;

export const PIN_SIZE = { pickup: 22, dropoff: 20, me: 18, stop: 16, searching: 22 } as const;

/** A gentle arc between two points, which reads as a route when no real route is known. */
export function arc(from: LatLng, to: LatLng, segments = 32): LatLng[] {
  const [lat1, lng1] = from;
  const [lat2, lng2] = to;
  const ctrl: LatLng = [(lat1 + lat2) / 2 - (lng2 - lng1) * 0.18, (lng1 + lng2) / 2 + (lat2 - lat1) * 0.18];
  const points: LatLng[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const a = (1 - t) * (1 - t);
    const b = 2 * (1 - t) * t;
    const c = t * t;
    points.push([a * lat1 + b * ctrl[0] + c * lat2, a * lng1 + b * ctrl[1] + c * lng2]);
  }
  return points;
}

/** Decode Google's encoded polyline format (used for real road routes). */
export function decodePolyline(encoded: string): LatLng[] {
  const points: LatLng[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    for (const coordinate of [0, 1]) {
      let shift = 0;
      let result = 0;
      let byte: number;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (coordinate === 0) lat += delta;
      else lng += delta;
    }
    points.push([lat / 1e5, lng / 1e5]);
  }
  return points;
}

/** The route to draw: the road polyline if known, else gentle arcs (through the stop, if any). */
export function routePath(from: LatLng, to: LatLng, encoded?: string | null, via?: LatLng | LatLng[] | null): LatLng[] {
  if (encoded) return decodePolyline(encoded);
  // `via` is one point ([lat, lng]) or a list of points (possibly empty: no stops).
  const stops: LatLng[] = !via || via.length === 0 ? [] : Array.isArray(via[0]) ? (via as LatLng[]) : [via as LatLng];
  const points = [from, ...stops, to];
  return points.slice(1).reduce<LatLng[]>((path, point, i) => [...path, ...arc(points[i], point).slice(i ? 1 : 0)], []);
}

/** The part of `path` still ahead of `position` (the whole path if the car isn't on it). */
export function remainingPath(path: LatLng[], position: LatLng | null | undefined): LatLng[] {
  if (!position) return path;
  const snap = snapToPath(path, position);
  if (!snap || snap.offMetres > 300) return path;
  return [snap.at, ...path.slice(snap.index + 1)];
}

export interface BaseMapProps {
  center: LatLng;
  zoom?: number;
  children?: React.ReactNode;
  zoomControl?: boolean;
  className?: string;
}

export interface CarMarkerProps {
  lat: number;
  lng: number;
  heading?: number | null;
  rideType?: string | null;
  label?: string;
  dim?: boolean;
  onClick?: () => void;
}

export interface PinMarkerProps {
  lat: number;
  lng: number;
  kind: keyof typeof PIN_HTML;
  label?: string;
}

export interface RouteLineProps {
  from: LatLng;
  to: LatLng;
  /** Encoded road polyline; when absent an arc is drawn. */
  encoded?: string | null;
  /** The car's position: the part of the route already driven is trimmed away. */
  progress?: LatLng | null;
  /** Stops on the way, in order (used when there's no road polyline). */
  via?: LatLng | LatLng[] | null;
  dashed?: boolean;
  color?: string;
}

export interface PolylineProps {
  positions: LatLng[];
  color: string;
  weight?: number;
  opacity?: number;
  dashed?: boolean;
}

export interface CircleProps {
  center: LatLng;
  radius: number; // metres
  color: string;
  fillOpacity?: number;
  weight?: number;
  label?: string;
  permanentLabel?: boolean;
}

export interface DotProps {
  center: LatLng;
  radius?: number; // pixels
  color: string;
  label?: string;
  onClick?: () => void;
}

export interface FitBoundsProps {
  points: LatLng[];
  padding?: number;
  /** A small map inside a card or dialog: no room kept for the desktop side panel. */
  inset?: boolean;
  bottom?: number;
  maxZoom?: number;
  /**
   * Refit only when this changes (e.g. the trip moves to a new stage). Without it the map refits
   * whenever the points change, which would fight the user on every GPS update.
   */
  fitKey?: string | number;
}

/** Move `stepKm` along `path` from the point on it nearest `point` (the demo autopilot's GPS). */
export function advanceAlong(path: LatLng[], point: LatLng, stepKm: number): { at: LatLng; heading: number; arrived: boolean } {
  const snap = snapToPath(path, point);
  if (!snap) return { at: path[path.length - 1] ?? point, heading: 0, arrived: true };
  let current = snap.at;
  let left = stepKm * 1000;
  for (let i = snap.index; i < path.length - 1; i++) {
    const next = path[i + 1];
    const segment = metresBetween(current, next);
    if (segment > left) {
      const f = left / segment;
      return { at: [current[0] + (next[0] - current[0]) * f, current[1] + (next[1] - current[1]) * f], heading: bearing(current, next), arrived: false };
    }
    left -= segment;
    current = next;
  }
  return { at: current, heading: bearing(path[path.length - 2], current), arrived: true };
}

export interface CenterWatchProps {
  onMoveStart?: () => void;
  /** Called with the map's centre once on mount and whenever the map comes to rest. */
  onMoveEnd: (lat: number, lng: number) => void;
}
