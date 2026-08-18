"use client";

import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Popup, TileLayer, ZoomControl, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L from "leaflet";
import type { DashboardMapPoint } from "@/lib/dashboardMap";
import { MapInitRecovery } from "@/components/map/MapInitRecovery";

const TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

const TYPE_COLORS: Record<string, string> = {
  farm: "#0f766e",
  dairyfarm: "#0f766e",
  processor: "#2563eb",
  cooperative: "#9333ea",
  distributioncenter: "#ea580c",
  "distribution center": "#ea580c",
  storagefacility: "#0891b2",
  "storage facility": "#0891b2",
  retailer: "#dc2626",
  facility: "#64748b",
};

const DEFAULT_COLOR = "#64748b";

function colorForType(type: string): string {
  const normalized = type.trim().toLowerCase().replace(/[_-]+/g, " ");
  return TYPE_COLORS[normalized] ?? TYPE_COLORS[normalized.replace(/\s+/g, "")] ?? DEFAULT_COLOR;
}

function createIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    iconSize: [22, 30],
    iconAnchor: [11, 30],
    popupAnchor: [0, -26],
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="30" viewBox="0 0 22 30" fill="none">
      <path d="M11 0C4.925 0 0 4.925 0 11c0 8.25 11 19 11 19s11-10.75 11-19C22 4.925 16.075 0 11 0z" fill="${color}"/>
      <circle cx="11" cy="10.5" r="4.2" fill="white" fill-opacity="0.9"/>
    </svg>`,
  });
}

const iconCache = new Map<string, L.DivIcon>();
function iconForType(type: string): L.DivIcon {
  const color = colorForType(type);
  let icon = iconCache.get(color);
  if (!icon) {
    icon = createIcon(color);
    iconCache.set(color, icon);
  }
  return icon;
}

function createClusterIcon(cluster: { getChildCount(): number }): L.DivIcon {
  const count = cluster.getChildCount();
  const size = count >= 100 ? 48 : count >= 30 ? 42 : 36;
  const color = count >= 100 ? "#dc2626" : count >= 30 ? "#ea580c" : "#2563eb";
  return L.divIcon({
    className: "",
    iconSize: L.point(size, size),
    iconAnchor: L.point(size / 2, size / 2),
    html: `<div style="
      align-items:center;
      background:${color};
      border:2px solid white;
      border-radius:9999px;
      box-shadow:0 8px 20px rgba(15,23,42,0.28);
      color:white;
      display:flex;
      font-size:12px;
      font-weight:700;
      height:${size}px;
      justify-content:center;
      width:${size}px;
    ">${count}</div>`,
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

const HIDDEN_PROPERTIES = new Set([
  "id",
  "name",
  "label",
  "type",
  "lat",
  "latitude",
  "lng",
  "lon",
  "longitude",
]);

function AutoFitBounds({ points }: { points: DashboardMapPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const bounds = L.latLngBounds(points.map((point) => [point.lat, point.lng] as [number, number]));
    map.fitBounds(bounds, { padding: [28, 28], maxZoom: 10 });
  }, [map, points]);
  return null;
}

function FacilityMarker({ point }: { point: DashboardMapPoint }) {
  const color = colorForType(point.type);
  const properties = Object.entries(point.properties).filter(
    ([key]) => !HIDDEN_PROPERTIES.has(key.toLowerCase()),
  );

  return (
    <Marker position={[point.lat, point.lng]} icon={iconForType(point.type)}>
      <Popup maxWidth={300} minWidth={190}>
        <div className="text-xs">
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-sm font-semibold leading-tight">{point.name}</span>
          </div>
          <div className="mb-2 text-[11px] text-gray-500">
            {point.type}
            {point.county ? ` · ${point.county}` : ""}
          </div>
          {properties.length > 0 ? (
            <table className="w-full border-collapse">
              <tbody>
                {properties.slice(0, 6).map(([key, value]) => (
                  <tr key={key} className="border-t border-gray-100">
                    <td className="py-0.5 pr-2 text-gray-500">{key.replace(/_/g, " ")}</td>
                    <td className="py-0.5 text-right font-medium">{formatValue(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </Popup>
    </Marker>
  );
}

export function FacilityLeafletMap({
  points,
  center,
  zoom,
}: {
  points: DashboardMapPoint[];
  center: [number, number];
  zoom: number;
}) {
  const legend = useMemo(() => {
    const counts = new Map<string, number>();
    for (const point of points) counts.set(point.type, (counts.get(point.type) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [points]);
  const clustered = points.length > 25;

  return (
    <div className="relative h-[340px] overflow-hidden rounded-lg border bg-muted">
      <MapInitRecovery>
      <MapContainer
        center={center}
        zoom={zoom}
        zoomControl={false}
        className="h-full w-full"
        attributionControl
      >
        <TileLayer attribution={TILE_ATTRIBUTION} url={TILE_URL} />
        <ZoomControl position="bottomright" />
        <AutoFitBounds points={points} />
        {clustered ? (
          <MarkerClusterGroup
            chunkedLoading
            maxClusterRadius={46}
            showCoverageOnHover={false}
            spiderfyOnMaxZoom
            iconCreateFunction={createClusterIcon}
          >
            {points.map((point) => (
              <FacilityMarker key={point.id} point={point} />
            ))}
          </MarkerClusterGroup>
        ) : (
          points.map((point) => <FacilityMarker key={point.id} point={point} />)
        )}
      </MapContainer>
      </MapInitRecovery>
      <div className="pointer-events-none absolute left-3 top-3 z-[1000] rounded-md border bg-background/90 px-2 py-1 text-xs shadow-sm backdrop-blur">
        {points.length.toLocaleString()} mapped nodes
      </div>
      <div className="absolute bottom-3 left-3 z-[1000] max-w-[calc(100%-1.5rem)] rounded-md border bg-background/90 px-2 py-1.5 text-xs shadow-sm backdrop-blur">
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {legend.slice(0, 6).map(([type, count]) => (
            <span key={type} className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colorForType(type) }} />
              {type}: {count.toLocaleString()}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
