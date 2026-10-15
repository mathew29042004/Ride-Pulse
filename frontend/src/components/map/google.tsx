/**
 * Google Maps renderer (@vis.gl/react-google-maps). Used when the server supplies a browser key.
 * Same component API as the Leaflet renderer, so pages don't care which one is active.
 */

import { Map as GoogleMap, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useMemo, useRef } from "react";

import { DESKTOP_PANEL_PX, useLayout } from "@/lib/layout";
import { useTheme } from "@/lib/theme";

import { useMapProvider } from "./provider";
import {
  type BaseMapProps,
  type CarMarkerProps,
  type CenterWatchProps,
  type CircleProps,
  type DotProps,
  type FitBoundsProps,
  type LatLng,
  type PinMarkerProps,
  PIN_HTML,
  type PolylineProps,
  type RouteLineProps,
  carHtml,
  remainingPath,
  rotateCar,
  routePath,
  useGlide,
  useHeading,
} from "./shared";

const toLiteral = ([lat, lng]: LatLng) => ({ lat, lng });

export function BaseMap({ center, zoom = 13, children, zoomControl = false, className }: BaseMapProps) {
  const [theme] = useTheme();
  const { mapId } = useMapProvider();
  return (
    <GoogleMap
      key={theme} // the colour scheme can only be chosen when the map is created
      className={className}
      style={{ height: "100%", width: "100%" }}
      defaultCenter={toLiteral(center)}
      defaultZoom={zoom}
      mapId={mapId}
      colorScheme={theme === "dark" ? "DARK" : "LIGHT"}
      disableDefaultUI
      zoomControl={zoomControl}
      clickableIcons={false}
      gestureHandling="greedy"
    >
      {children}
    </GoogleMap>
  );
}

/**
 * Markers are created imperatively with google.maps.marker.AdvancedMarkerElement. Every call is
 * guarded: if Google breaks at runtime (e.g. the key is rejected), the app fails over to
 * OpenStreetMap instead of crashing the screen.
 */
function useMarker({
  lat,
  lng,
  html,
  zIndex = 1,
  title,
  onClick,
  glide = false,
}: {
  lat: number;
  lng: number;
  html: string;
  zIndex?: number;
  title?: string;
  onClick?: () => void;
  /** Animate moves (cars) instead of jumping (pins). */
  glide?: boolean;
}) {
  const map = useMap();
  const { fail } = useMapProvider();
  const marker = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const click = useRef(onClick);
  click.current = onClick;
  const shown = useRef<LatLng>([lat, lng]);

  useEffect(() => {
    if (!map || !google.maps.marker?.AdvancedMarkerElement) return;
    const content = document.createElement("div");
    content.style.transform = "translateY(50%)"; // anchor at the centre, not the bottom
    try {
      marker.current = new google.maps.marker.AdvancedMarkerElement({ map, content, zIndex, title, position: toLiteral(shown.current) });
      marker.current.addListener("click", () => click.current?.());
    } catch (error) {
      fail(String(error));
    }
    return () => {
      try {
        if (marker.current) marker.current.map = null;
      } catch {
        /* the map may already be gone */
      }
      marker.current = null;
    };
  }, [map]); // eslint-disable-line react-hooks/exhaustive-deps

  const place = (position: LatLng) => {
    shown.current = position;
    try {
      if (marker.current) marker.current.position = toLiteral(position);
    } catch (error) {
      fail(String(error));
    }
  };
  useGlide(lat, lng, (position) => glide && place(position));
  useEffect(() => {
    if (!glide) place([lat, lng]);
  }, [map, lat, lng, glide]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const current = marker.current;
    if (!current) return;
    try {
      current.zIndex = zIndex;
      (current.content as HTMLElement).innerHTML = html;
    } catch (error) {
      fail(String(error));
    }
  }, [map, html, zIndex, fail]);
  return marker;
}

export function CarMarker({ lat, lng, heading, rideType, label, dim = false, onClick }: CarMarkerProps) {
  const html = carHtml(rideType, dim);
  const marker = useMarker({ lat, lng, html, zIndex: dim ? 1 : 5, title: label, onClick, glide: true });
  const angle = useHeading(lat, lng, heading);
  const map = useMap(); // the marker only exists once the map does
  useEffect(() => {
    rotateCar(marker.current?.content as HTMLElement | undefined, angle);
  }, [map, angle, html]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function PinMarker({ lat, lng, kind, label }: PinMarkerProps) {
  const chip = label
    ? `<span style="position:absolute;bottom:28px;left:50%;transform:translateX(-50%);white-space:nowrap;background:#fff;color:#0b0f19;border-radius:8px;padding:2px 8px;font:600 12px var(--font-sans);box-shadow:0 2px 6px rgba(0,0,0,.2)">${label}</span>`
    : "";
  useMarker({ lat, lng, html: `<div style="position:relative">${chip}${PIN_HTML[kind]}</div>`, zIndex: 10 });
  return null;
}

/**
 * Imperative wrapper around google.maps.Polyline: one instance per mount, updated in place and
 * removed on unmount. (Simpler and sturdier than re-creating overlays from props.)
 */
function useOverlay<T extends google.maps.MVCObject & { setMap(map: google.maps.Map | null): void }>(
  create: () => T,
  update: (overlay: T) => void,
  deps: unknown[],
) {
  const map = useMap();
  const { fail } = useMapProvider();
  const overlay = useRef<T | null>(null);
  useEffect(() => {
    if (!map) return;
    try {
      overlay.current = create();
      overlay.current.setMap(map);
    } catch (error) {
      fail(String(error));
    }
    return () => {
      try {
        overlay.current?.setMap(null);
      } catch {
        /* the map may already be gone */
      }
      overlay.current = null;
    };
  }, [map]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    try {
      if (overlay.current) update(overlay.current);
    } catch (error) {
      fail(String(error));
    }
  }, [map, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function MapPolyline({ positions, color, weight = 4, opacity = 1, dashed = false }: PolylineProps) {
  const key = JSON.stringify(positions);
  useOverlay(
    () => new google.maps.Polyline({ clickable: false }),
    (line) =>
      line.setOptions({
        path: positions.map(toLiteral),
        strokeColor: color,
        strokeWeight: weight,
        strokeOpacity: dashed ? 0 : opacity,
        icons: dashed
          ? [{ icon: { path: "M 0,-1 0,1", strokeOpacity: opacity, strokeColor: color, scale: weight }, offset: "0", repeat: `${weight * 4}px` }]
          : [],
      }),
    [key, color, weight, opacity, dashed],
  );
  return null;
}

export function RouteLine({ from, to, encoded, dashed = false, color, progress, via }: RouteLineProps) {
  const [theme] = useTheme();
  const path = useMemo(() => routePath(from, to, encoded, via), [from[0], from[1], to[0], to[1], encoded, JSON.stringify(via ?? null)]); // eslint-disable-line react-hooks/exhaustive-deps
  const positions = useMemo(() => remainingPath(path, progress), [path, progress?.[0], progress?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  const stroke = color ?? (theme === "dark" ? "#f2f4f7" : "#0b0f19");
  return (
    <>
      {!dashed && <MapPolyline positions={positions} color="#ffffff" weight={8} opacity={0.85} />}
      <MapPolyline positions={positions} color={stroke} weight={dashed ? 3 : 5} dashed={dashed} />
    </>
  );
}

function CircleLabel({ center, label }: { center: LatLng; label: string }) {
  useMarker({ lat: center[0], lng: center[1], html: `<span style="font:700 12px var(--font-sans);color:#b45309">${label}</span>` });
  return null;
}

export function MapCircle({ center, radius, color, fillOpacity = 0.15, weight = 1, label, permanentLabel = false }: CircleProps) {
  useOverlay(
    () => new google.maps.Circle({ clickable: false }),
    (circle) =>
      circle.setOptions({ center: toLiteral(center), radius, strokeColor: color, strokeWeight: weight, fillColor: color, fillOpacity }),
    [center[0], center[1], radius, color, fillOpacity, weight],
  );
  return label && permanentLabel ? <CircleLabel center={center} label={label} /> : null;
}

export function MapDot({ center, radius = 6, color, label, onClick }: DotProps) {
  const size = radius * 2;
  useMarker({
    lat: center[0],
    lng: center[1],
    html: `<div style="width:${size}px;height:${size}px;border-radius:999px;background:${color};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.3)"></div>`,
    zIndex: 3,
    title: label,
    onClick,
  });
  return null;
}

export function FitBounds({ points, padding = 60, bottom, maxZoom = 16, fitKey }: FitBoundsProps) {
  const map = useMap();
  const key = fitKey ?? JSON.stringify(points.map(([a, b]) => [a.toFixed(3), b.toFixed(3)]));
  const desktop = useLayout().mode === "desktop";
  useEffect(() => {
    if (!map || !points.length) return;
    if (points.length === 1) {
      map.panTo(toLiteral(points[0]));
      map.setZoom(Math.min(maxZoom, 15));
      return;
    }
    const bounds = new google.maps.LatLngBounds();
    points.forEach((p) => bounds.extend(toLiteral(p)));
    // Desktop: keep the route clear of the side panel on the left, not a bottom sheet.
    map.fitBounds(bounds, {
      top: padding,
      left: padding + (desktop ? DESKTOP_PANEL_PX : 0),
      right: padding,
      bottom: desktop ? padding : (bottom ?? padding),
    });
    const listener = map.addListener("idle", () => {
      if ((map.getZoom() ?? 0) > maxZoom) map.setZoom(maxZoom);
      listener.remove();
    });
    return () => listener.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map, bottom, desktop]);
  return null;
}

export function Recenter({ center, zoom }: { center: LatLng; zoom?: number }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    map.panTo(toLiteral(center));
    if (zoom) map.setZoom(zoom);
  }, [center[0], center[1], zoom, map]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function MapClick({ onClick }: { onClick: (lat: number, lng: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const listener = map.addListener("click", (e: google.maps.MapMouseEvent) => {
      if (e.latLng) onClick(e.latLng.lat(), e.latLng.lng());
    });
    return () => listener.remove();
  }, [map, onClick]);
  return null;
}

export function MapCenterWatch({ onMoveStart, onMoveEnd }: CenterWatchProps) {
  const map = useMap();
  const handlers = useRef({ onMoveStart, onMoveEnd });
  handlers.current = { onMoveStart, onMoveEnd };
  useEffect(() => {
    if (!map) return;
    const report = () => {
      const c = map.getCenter();
      if (c) handlers.current.onMoveEnd(c.lat(), c.lng());
    };
    report();
    const start = map.addListener("dragstart", () => handlers.current.onMoveStart?.());
    const idle = map.addListener("idle", report);
    return () => {
      start.remove();
      idle.remove();
    };
  }, [map]);
  return null;
}
