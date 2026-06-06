"use client";

import { useEffect, useRef, useMemo } from "react";
import { useMap, Polyline, Popup } from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";
import type { MapRoute, MapLayer } from "@/lib/types";

// ─── Color scale by volume ──────────────────────────────────────────────────

const ROUTE_COLORS = [
  "#22c55e", // green — low
  "#eab308", // yellow — medium
  "#f97316", // orange — medium-high
  "#ef4444", // red — high
];

function getRouteColor(value: number, min: number, max: number): string {
  if (max === min) return ROUTE_COLORS[1];
  const t = (value - min) / (max - min);
  const idx = Math.min(Math.floor(t * ROUTE_COLORS.length), ROUTE_COLORS.length - 1);
  return ROUTE_COLORS[idx];
}

function getRouteWeight(value: number, min: number, max: number): number {
  if (max === min) return 3;
  const t = (value - min) / (max - min);
  return 2 + t * 4; // 2px to 6px
}

// ─── Arrow decorator using a midpoint SVG marker ────────────────────────────

function ArrowHead({
  from,
  to,
  color,
}: {
  from: [number, number];
  to: [number, number];
  color: string;
}) {
  const map = useMap();
  const markerRef = useRef<L.Marker | null>(null);

  useEffect(() => {
    // Compute midpoint
    const midLat = (from[0] + to[0]) / 2;
    const midLng = (from[1] + to[1]) / 2;

    // Compute bearing for arrow rotation
    const fromPt = map.latLngToContainerPoint(L.latLng(from[0], from[1]));
    const toPt = map.latLngToContainerPoint(L.latLng(to[0], to[1]));
    const angle = Math.atan2(toPt.y - fromPt.y, toPt.x - fromPt.x) * (180 / Math.PI);

    const icon = L.divIcon({
      className: "",
      iconSize: [14, 14],
      iconAnchor: [7, 7],
      html: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" style="transform: rotate(${angle}deg)">
        <polygon points="0,2 14,7 0,12" fill="${color}" opacity="0.85"/>
      </svg>`,
    });

    const marker = L.marker([midLat, midLng], { icon, interactive: false }).addTo(map);
    markerRef.current = marker;

    return () => {
      if (markerRef.current) {
        map.removeLayer(markerRef.current);
      }
    };
  }, [map, from, to, color]);

  return null;
}

// ─── Format property value ──────────────────────────────────────────────────

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

// ─── Single route line ──────────────────────────────────────────────────────

function RouteLine({
  route,
  color,
  weight,
}: {
  route: MapRoute;
  color: string;
  weight: number;
}) {
  const positions: [number, number][] = [route.from, route.to];

  const displayProps = route.properties
    ? Object.entries(route.properties)
    : [];

  return (
    <>
      <Polyline
        positions={positions}
        pathOptions={{
          color,
          weight,
          opacity: 0.75,
          dashArray: undefined,
        }}
      >
        <Popup maxWidth={250} minWidth={160}>
          <div className="text-xs">
            <div className="mb-1 font-semibold">
              {route.label ?? "Supply Route"}
            </div>
            <table className="w-full border-collapse">
              <tbody>
                <tr className="border-t border-gray-100">
                  <td className="py-0.5 pr-2 text-gray-500">Origin</td>
                  <td className="py-0.5 text-right font-medium">
                    {route.from[0].toFixed(3)}, {route.from[1].toFixed(3)}
                  </td>
                </tr>
                <tr className="border-t border-gray-100">
                  <td className="py-0.5 pr-2 text-gray-500">Destination</td>
                  <td className="py-0.5 text-right font-medium">
                    {route.to[0].toFixed(3)}, {route.to[1].toFixed(3)}
                  </td>
                </tr>
                {displayProps.map(([key, value]) => (
                  <tr key={key} className="border-t border-gray-100">
                    <td className="py-0.5 pr-2 text-gray-500 capitalize">
                      {key.replace(/_/g, " ")}
                    </td>
                    <td className="py-0.5 text-right font-medium">
                      {formatValue(value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Popup>
      </Polyline>
      <ArrowHead from={route.from} to={route.to} color={color} />
    </>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function MapRoutes() {
  const layers = useMapStore((s) => s.layers);

  // Collect all routes from all visible route layers
  const routes = useMemo(() => {
    const routeLayers = layers.filter(
      (l): l is MapLayer & { type: "routes"; data: MapRoute[] } =>
        l.type === "routes" && l.visible
    );
    return routeLayers.flatMap((l) => l.data as MapRoute[]);
  }, [layers]);

  // Compute volume range for color scale
  const { min, max } = useMemo(() => {
    const volumes = routes
      .map((r) => {
        const p = r.properties ?? {};
        const v = p.volume_lbs ?? p.volume ?? p.cost_per_mile ?? p.cost_per_unit ?? p.distance_miles;
        return typeof v === "number" ? v : null;
      })
      .filter((v): v is number => v !== null);
    if (volumes.length === 0) return { min: 0, max: 1 };
    return { min: Math.min(...volumes), max: Math.max(...volumes) };
  }, [routes]);

  if (routes.length === 0) return null;

  return (
    <>
      {routes.map((route) => {
        const p = route.properties ?? {};
        const vol =
          typeof p.volume_lbs === "number" ? p.volume_lbs
            : typeof p.volume === "number" ? p.volume
            : typeof p.cost_per_mile === "number" ? p.cost_per_mile
            : typeof p.cost_per_unit === "number" ? p.cost_per_unit
            : typeof p.distance_miles === "number" ? p.distance_miles
            : (min + max) / 2;

        return (
          <RouteLine
            key={route.id}
            route={route}
            color={getRouteColor(vol as number, min, max)}
            weight={getRouteWeight(vol as number, min, max)}
          />
        );
      })}
    </>
  );
}
