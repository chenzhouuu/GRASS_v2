"use client";

import MarkerClusterGroup from "react-leaflet-cluster";
import { Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";
import { MapPopupActions } from "./MapPopupActions";
import type { MapMarker as MapMarkerType } from "@/lib/types";

// ─── Reuse marker icon logic from MapMarkers ───────────────────────────────

const MARKER_COLORS: Record<string, string> = {
  farm: "#16a34a",
  producer: "#16a34a",
  company: "#2563eb",
  processor: "#2563eb",
  distributor: "#ea580c",
  warehouse: "#7c3aed",
  location: "#64748b",
};

const DEFAULT_COLOR = "#6b7280";

function getMarkerColor(type?: string): string {
  if (!type) return DEFAULT_COLOR;
  return MARKER_COLORS[type.toLowerCase()] ?? DEFAULT_COLOR;
}

function createIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    iconSize: [24, 34],
    iconAnchor: [12, 34],
    popupAnchor: [0, -30],
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="34" viewBox="0 0 24 34" fill="none">
      <path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 22 12 22s12-13 12-22C24 5.373 18.627 0 12 0z" fill="${color}"/>
      <circle cx="12" cy="11" r="5" fill="white" fill-opacity="0.9"/>
    </svg>`,
  });
}

const iconCache = new Map<string, L.DivIcon>();
function getIcon(color: string): L.DivIcon {
  let icon = iconCache.get(color);
  if (!icon) {
    icon = createIcon(color);
    iconCache.set(color, icon);
  }
  return icon;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

const EXCLUDED_PROPS = new Set([
  "id", "lat", "latitude", "lng", "lon", "longitude",
  "label", "name", "type",
]);

// ─── Custom cluster icon ────────────────────────────────────────────────────

function createClusterIcon(cluster: { getChildCount(): number }): L.DivIcon {
  const count = cluster.getChildCount();
  let size = 36;
  let bg = "#3b82f6"; // blue
  if (count >= 50) {
    size = 48;
    bg = "#dc2626"; // red
  } else if (count >= 20) {
    size = 42;
    bg = "#f59e0b"; // amber
  }

  return L.divIcon({
    html: `<div style="
      background: ${bg};
      color: white;
      width: ${size}px;
      height: ${size}px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 600;
      box-shadow: 0 2px 6px rgba(0,0,0,0.3);
      border: 2px solid white;
    ">${count}</div>`,
    className: "",
    iconSize: L.point(size, size),
    iconAnchor: L.point(size / 2, size / 2),
  });
}

// ─── Clustered marker with popup ────────────────────────────────────────────

function ClusteredMarker({ marker }: { marker: MapMarkerType }) {
  const setSelectedMarker = useMapStore((s) => s.setSelectedMarker);
  const color = getMarkerColor(marker.type);
  const icon = getIcon(color);

  const displayProps = marker.properties
    ? Object.entries(marker.properties).filter(
        ([key]) => !EXCLUDED_PROPS.has(key.toLowerCase())
      )
    : [];

  return (
    <Marker
      position={[marker.lat, marker.lng]}
      icon={icon}
      eventHandlers={{ click: () => setSelectedMarker(marker.id) }}
    >
      <Popup maxWidth={280} minWidth={180}>
        <div className="text-xs">
          <div className="mb-1.5 flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="font-semibold text-sm leading-tight">
              {marker.label}
            </span>
          </div>
          {marker.type && (
            <div className="mb-1.5 text-[11px] text-gray-500">{marker.type}</div>
          )}
          {displayProps.length > 0 && (
            <table className="w-full border-collapse">
              <tbody>
                {displayProps.slice(0, 6).map(([key, value]) => (
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
          )}
          <MapPopupActions marker={marker} />
        </div>
      </Popup>
    </Marker>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function MapClusters() {
  const markers = useMapStore((s) => s.markers);

  if (markers.length === 0) return null;

  return (
    <MarkerClusterGroup
      chunkedLoading
      maxClusterRadius={50}
      spiderfyOnMaxZoom
      showCoverageOnHover={false}
      iconCreateFunction={createClusterIcon}
    >
      {markers.map((marker) => (
        <ClusteredMarker key={marker.id} marker={marker} />
      ))}
    </MarkerClusterGroup>
  );
}
