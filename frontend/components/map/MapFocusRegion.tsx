"use client";

import { Rectangle } from "react-leaflet";
import { useMapStore } from "@/stores/mapStore";

function parseBbox(
  bbox: string | null,
): [[number, number], [number, number]] | null {
  if (!bbox) return null;
  const parts = bbox.split(",").map((v) => Number(v.trim()));
  if (parts.length !== 4 || parts.some((v) => Number.isNaN(v))) return null;
  const [swLat, swLng, neLat, neLng] = parts;
  return [
    [swLat, swLng],
    [neLat, neLng],
  ];
}

export function MapFocusRegion() {
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);
  const bounds = parseBbox(selectedRegionBbox);
  if (!bounds) return null;

  return (
    <Rectangle
      bounds={bounds}
      pathOptions={{
        color: "#2563eb",
        weight: 2,
        fillColor: "#2563eb",
        fillOpacity: 0.08,
        dashArray: "6 3",
      }}
    />
  );
}
