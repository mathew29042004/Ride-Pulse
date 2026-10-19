/** OpenStreetMap renderer (Leaflet). Used when no Google Maps browser key is configured. */

import L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";

import { DESKTOP_PANEL_PX, useLayout } from "@/lib/layout";
import { useTheme } from "@/lib/theme";

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
  PIN_SIZE,
  type PolylineProps,
  type RouteLineProps,
  carHtml,
  remainingPath,
  rotateCar,
  routePath,
  useGlide,
  useHeading,
} from "./shared";

// OpenStreetMap's standard tiles need no API key (fine for a demo; production traffic should use
// Google Maps or a commercial tile provider). Dark mode re-colours the tiles with a CSS filter.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export function BaseMap({ center, zoom = 13, children, zoomControl = false, className }: BaseMapProps) {
  const [theme] = useTheme();
  return (
    <MapContainer
      center={center}
      zoom={zoom}
      zoomControl={zoomControl}
      // isolate: Leaflet's pane z-indexes stay inside the map instead of competing with
      // overlays such as bottom sheets.
      className={`isolate ${className ?? ""}`}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        key={theme}
        url={TILE_URL}
        attribution={ATTRIBUTION}
        maxZoom={19}
        // OpenStreetMap refuses tiles without a Referer, so never let a stricter page policy drop it.
        referrerPolicy="strict-origin-when-cross-origin"
        className={theme === "dark" ? "rp-tiles-dark" : undefined}
      />
      <AutoResize />
      {children}
    </MapContainer>
  );
}

/** Leaflet only notices window resizes; this also catches the container changing size on its own. */
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
}

const iconCache = new Map<string, L.DivIcon>();

function cachedIcon(key: string, html: string, size: number) {
  let icon = iconCache.get(key);
  if (!icon) {
    icon = L.divIcon({ className: "rp-marker", html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
    iconCache.set(key, icon);
  }
  return icon;
}

export function CarMarker({ lat, lng, heading, rideType, label, dim = false, onClick }: CarMarkerProps) {
  const marker = useRef<L.Marker | null>(null);
  // Leaflet owns the position after mount; useGlide moves it, React never resets it.
  const [start] = useState<LatLng>(() => [lat, lng]);
  const icon = cachedIcon(`car-${rideType}-${dim}`, carHtml(rideType, dim), 30);
  const angle = useHeading(lat, lng, heading);
  useGlide(lat, lng, (position) => marker.current?.setLatLng(position));
  useEffect(() => {
    rotateCar(marker.current?.getElement(), angle);
  }, [angle, icon]);
  return (
    <Marker
      ref={marker}
      position={start}
      icon={icon}
      eventHandlers={onClick ? { click: onClick } : undefined}
      zIndexOffset={dim ? 0 : 500}
      // Screen readers: name the car; only clickable cars take keyboard focus.
      title={label ?? rideType ?? "Car"}
      alt={label ?? rideType ?? "Car"}
      keyboard={!!onClick}
    >
      {label && (
        <Tooltip direction="top" offset={[0, -12]}>
          {label}
        </Tooltip>
      )}
    </Marker>
  );
}

export function PinMarker({ lat, lng, kind, label }: PinMarkerProps) {
  const icon = cachedIcon(`pin-${kind}`, PIN_HTML[kind], PIN_SIZE[kind]);
  return (
    <Marker position={[lat, lng]} icon={icon} zIndexOffset={1000} title={label ?? kind} alt={label ?? kind} keyboard={false}>
      {label && (
        <Tooltip direction="top" offset={[0, -10]} permanent className="!rounded-lg !border-0 !px-2 !py-1 !text-xs !font-semibold !shadow-md">
          {label}
        </Tooltip>
      )}
    </Marker>
  );
}

export function MapPolyline({ positions, color, weight = 4, opacity = 1, dashed = false }: PolylineProps) {
  return <Polyline positions={positions} pathOptions={{ color, weight, opacity, dashArray: dashed ? "6 8" : undefined, lineCap: "round" }} />;
}

export function RouteLine({ from, to, encoded, dashed = false, color, progress, via }: RouteLineProps) {
  const [theme] = useTheme();
  const path = useMemo(() => routePath(from, to, encoded, via), [from[0], from[1], to[0], to[1], encoded, JSON.stringify(via ?? null)]); // eslint-disable-line react-hooks/exhaustive-deps
  const positions = useMemo(() => remainingPath(path, progress), [path, progress?.[0], progress?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  const stroke = color ?? (theme === "dark" ? "#f2f4f7" : "#0b0f19");
  return (
    <>
      {!dashed && <MapPolyline positions={positions} color="white" weight={8} opacity={0.85} />}
      <MapPolyline positions={positions} color={stroke} weight={dashed ? 3 : 4.5} dashed={dashed} />
    </>
  );
}

export function MapCircle({ center, radius, color, fillOpacity = 0.15, weight = 1, label, permanentLabel = false }: CircleProps) {
  return (
    <Circle center={center} radius={radius} pathOptions={{ color, weight, fillColor: color, fillOpacity }}>
      {label && (
        <Tooltip direction="center" permanent={permanentLabel} className={permanentLabel ? "!border-0 !bg-transparent !shadow-none !text-xs !font-bold" : undefined}>
          {label}
        </Tooltip>
      )}
    </Circle>
  );
}

export function MapDot({ center, radius = 6, color, label, onClick }: DotProps) {
  return (
    <CircleMarker center={center} radius={radius} pathOptions={{ color: "white", weight: 2, fillColor: color, fillOpacity: 1 }} eventHandlers={onClick ? { click: onClick } : undefined}>
      {label && <Tooltip>{label}</Tooltip>}
    </CircleMarker>
  );
}

export function FitBounds({ points, padding = 60, bottom, maxZoom = 16, fitKey, inset = false }: FitBoundsProps) {
  const map = useMap();
  const key = fitKey ?? JSON.stringify(points.map(([a, b]) => [a.toFixed(3), b.toFixed(3)]));
  const first = useRef(true);
  const desktop = useLayout().mode === "desktop" && !inset;
  useEffect(() => {
    if (!points.length) return;
    // Desktop: keep the route clear of the side panel on the left, not a bottom sheet.
    const options = {
      paddingTopLeft: [padding + (desktop ? DESKTOP_PANEL_PX : 0), padding] as L.PointTuple,
      paddingBottomRight: [padding, desktop ? padding : (bottom ?? padding)] as L.PointTuple,
      maxZoom,
      // The first fit jumps straight there; zooming out from the initial view looks like a glitch.
      animate: !first.current,
    };
    first.current = false;
    map.invalidateSize(); // the container may have just appeared (a dialog opening)
    const bounds = points.length === 1 ? L.latLngBounds([points[0], points[0]]) : L.latLngBounds(points);
    map.fitBounds(bounds, points.length === 1 ? { ...options, maxZoom: Math.min(maxZoom, 15) } : options);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map, bottom, desktop]);
  return null;
}

export function Recenter({ center, zoom }: { center: LatLng; zoom?: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom ?? map.getZoom(), { animate: true });
  }, [center[0], center[1], zoom, map]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function MapClick({ onClick }: { onClick: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onClick(e.latlng.lat, e.latlng.lng) });
  return null;
}

export function MapCenterWatch({ onMoveStart, onMoveEnd }: CenterWatchProps) {
  const map = useMapEvents({
    movestart: () => onMoveStart?.(),
    moveend: () => {
      const c = map.getCenter();
      onMoveEnd(c.lat, c.lng);
    },
  });
  useEffect(() => {
    const c = map.getCenter();
    onMoveEnd(c.lat, c.lng);
  }, [map]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
