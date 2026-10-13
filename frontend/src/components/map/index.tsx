/**
 * Provider-agnostic map components. Pages use these; each one renders the Google Maps or the
 * OpenStreetMap (Leaflet) implementation depending on the server's configuration.
 */

import * as G from "./google";
import * as OSM from "./leaflet";
import { GoogleMapBoundary, useMapProvider } from "./provider";
import type {
  BaseMapProps,
  CarMarkerProps,
  CenterWatchProps,
  CircleProps,
  DotProps,
  FitBoundsProps,
  LatLng,
  PinMarkerProps,
  PolylineProps,
  RouteLineProps,
} from "./shared";

export { MapsProvider, configQuery, useMapProvider } from "./provider";
export { RIDE_TYPE_COLORS, advanceAlong, arc, decodePolyline, routePath, snapToPath, type LatLng } from "./shared";

const useGoogle = () => useMapProvider().provider === "google";

export function BaseMap(props: BaseMapProps) {
  const { provider, fail } = useMapProvider();
  if (provider === "google") {
    return (
      <GoogleMapBoundary onFail={fail}>
        <G.BaseMap {...props} />
      </GoogleMapBoundary>
    );
  }
  return <OSM.BaseMap {...props} />;
}

export function CarMarker(props: CarMarkerProps) {
  return useGoogle() ? <G.CarMarker {...props} /> : <OSM.CarMarker {...props} />;
}

export function PinMarker(props: PinMarkerProps) {
  return useGoogle() ? <G.PinMarker {...props} /> : <OSM.PinMarker {...props} />;
}

export function RouteLine(props: RouteLineProps) {
  return useGoogle() ? <G.RouteLine {...props} /> : <OSM.RouteLine {...props} />;
}

export function MapPolyline(props: PolylineProps) {
  return useGoogle() ? <G.MapPolyline {...props} /> : <OSM.MapPolyline {...props} />;
}

export function MapCircle(props: CircleProps) {
  return useGoogle() ? <G.MapCircle {...props} /> : <OSM.MapCircle {...props} />;
}

export function MapDot(props: DotProps) {
  return useGoogle() ? <G.MapDot {...props} /> : <OSM.MapDot {...props} />;
}

export function FitBounds(props: FitBoundsProps) {
  return useGoogle() ? <G.FitBounds {...props} /> : <OSM.FitBounds {...props} />;
}

export function Recenter(props: { center: LatLng; zoom?: number }) {
  return useGoogle() ? <G.Recenter {...props} /> : <OSM.Recenter {...props} />;
}

export function MapClick(props: { onClick: (lat: number, lng: number) => void }) {
  return useGoogle() ? <G.MapClick {...props} /> : <OSM.MapClick {...props} />;
}

/** Reports the map centre when the user stops panning (for "move the map to set the pin"). */
export function MapCenterWatch(props: CenterWatchProps) {
  return useGoogle() ? <G.MapCenterWatch {...props} /> : <OSM.MapCenterWatch {...props} />;
}
