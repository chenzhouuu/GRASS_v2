"use client";

import { Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";
import { MapPopupActions } from "./MapPopupActions";
import type { MapMarker as MapMarkerType } from "@/lib/types";

// ─── Color-coded marker icons by entity type ────────────────────────────────

const MARKER_COLORS: Record<string, string> = {
  farm: "#16a34a",            // green-600
  dairyfarm: "#16a34a",       // green-600
  producer: "#16a34a",        // green-600
  cooperative: "#059669",     // emerald-600
  processor: "#2563eb",       // blue-600
  company: "#2563eb",         // blue-600
  distributor: "#ea580c",     // orange-600
  distributioncenter: "#ea580c",
  warehouse: "#7c3aed",       // violet-600
  storagefacility: "#7c3aed", // violet-600
  retailer: "#dc2626",        // red-600
  location: "#64748b",        // slate-500
};

const DEFAULT_COLOR = "#6b7280"; // gray-500

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

// Cache icons to avoid re-creating on every render
const iconCache = new Map<string, L.DivIcon>();
function getIcon(color: string): L.DivIcon {
  let icon = iconCache.get(color);
  if (!icon) {
    icon = createIcon(color);
    iconCache.set(color, icon);
  }
  return icon;
}

// ─── Format property values for popup ───────────────────────────────────────

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

// Properties to exclude from popup detail list
const EXCLUDED_PROPS = new Set([
  "id", "lat", "latitude", "lng", "lon", "longitude",
  "label", "name", "type",
]);

// ─── Single marker with popup ───────────────────────────────────────────────

function MarkerWithPopup({ marker }: { marker: MapMarkerType }) {
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
      eventHandlers={{
        click: () => setSelectedMarker(marker.id),
      }}
    >
      <Popup maxWidth={280} minWidth={180}>
        <div className="text-xs">
          {/* Header */}
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

          {/* Properties table */}
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

          {/* Action buttons — sends query to chat automatically */}
          <MapPopupActions marker={marker} />
        </div>
      </Popup>
    </Marker>
  );
}

// ─── Markers layer ──────────────────────────────────────────────────────────

export function MapMarkers() {
  const markers = useMapStore((s) => s.markers);

  if (markers.length === 0) return null;

  return (
    <>
      {markers.map((marker) => (
        <MarkerWithPopup key={marker.id} marker={marker} />
      ))}
    </>
  );
}
