"use client";

import { useMemo, useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";

/**
 * Renders optimization routes as OSRM-resolved road paths with
 * origin/destination markers on the Leaflet map.
 *
 * Uses Leaflet's native L.geoJSON for multi-point LineString rendering
 * (preserving 100-2000+ waypoints from OSRM road resolution).
 *
 * Design: routes are colored by volume on a blue gradient, with
 * circle markers at origin (blue) and destination (orange) endpoints.
 */

// ─── Color palette ──────────────────────────────────────────────────────────

// Blue gradient for routes (low → high volume)
const ROUTE_PALETTE = [
  "#93c5fd", // blue-300 — low volume
  "#60a5fa", // blue-400
  "#3b82f6", // blue-500
  "#2563eb", // blue-600
  "#1d4ed8", // blue-700 — high volume
];

const ORIGIN_COLOR = "#2563eb";  // blue-600 (processor)
const DEST_COLOR = "#f97316";    // orange-500 (distribution center)

function getRouteColor(t: number): string {
  const idx = Math.min(
    Math.floor(t * ROUTE_PALETTE.length),
    ROUTE_PALETTE.length - 1
  );
  return ROUTE_PALETTE[idx];
}

function getRouteWeight(t: number): number {
  return 2.5 + t * 3; // 2.5px (low) to 5.5px (high)
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") {
    if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (Math.abs(value) >= 1) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

// ─── Endpoint marker icon factories ─────────────────────────────────────────

function createLabeledIcon(color: string, label: string, size: number = 18): L.DivIcon {
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
    html: `<div style="
      width:${size}px; height:${size}px; border-radius:50%;
      background:${color}; border:2.5px solid white;
      box-shadow:0 1px 6px rgba(0,0,0,0.35);
      display:flex; align-items:center; justify-content:center;
    " title="${label}">
      <svg xmlns="http://www.w3.org/2000/svg" width="${size - 8}" height="${size - 8}" viewBox="0 0 16 16" fill="white">
        <circle cx="8" cy="8" r="3"/>
      </svg>
    </div>`,
  });
}

// ─── Component ──────────────────────────────────────────────────────────────

export function MapRoutesGeoJSON() {
  const routeGeoJson = useMapStore((s) => s.routeGeoJson);
  const layerVisibility = useMapStore((s) => s.layerVisibility);
  const map = useMap();
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  // Compute volume range for normalization
  const { minVol, maxVol } = useMemo(() => {
    if (!routeGeoJson?.features?.length) return { minVol: 0, maxVol: 1 };
    const volumes = routeGeoJson.features
      .map((f) => {
        const p = (f as unknown as Record<string, unknown>).properties as Record<string, unknown> | undefined;
        const v = p?.volume_lbs ?? p?.volume;
        return typeof v === "number" ? v : null;
      })
      .filter((v): v is number => v !== null);
    if (volumes.length === 0) return { minVol: 0, maxVol: 1 };
    return { minVol: Math.min(...volumes), maxVol: Math.max(...volumes) };
  }, [routeGeoJson]);

  useEffect(() => {
    // Clean up previous layer group
    if (layerGroupRef.current) {
      map.removeLayer(layerGroupRef.current);
      layerGroupRef.current = null;
    }

    if (!routeGeoJson?.features?.length || !layerVisibility.routes) return;

    const group = L.layerGroup();

    // Collect endpoints with full route info for summary popups
    type EndpointInfo = {
      lat: number; lon: number; type: "origin" | "dest"; name: string;
      connections: { name: string; volume: number; distance: number }[];
    };
    const endpoints = new Map<string, EndpointInfo>();

    // Add route lines
    const geoJsonLayer = L.geoJSON(routeGeoJson as GeoJSON.FeatureCollection, {
      style: (feature) => {
        if (!feature) return {};
        const props = feature.properties ?? {};
        const vol = (props.volume_lbs ?? props.volume ?? 0) as number;
        const t = maxVol === minVol ? 0.5 : (vol - minVol) / (maxVol - minVol);
        return {
          color: getRouteColor(t),
          weight: getRouteWeight(t),
          opacity: 0.8,
          smoothFactor: 1.5,
          lineCap: "round" as L.LineCapShape,
          lineJoin: "round" as L.LineJoinShape,
        };
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties ?? {};
        const originName = (props.origin_name ?? "Origin") as string;
        const destName = (props.dest_name ?? "Destination") as string;
        const volume = props.volume_lbs as number | undefined;
        const cost = props.cost as number | undefined;

        // Build popup — detect if cost represents distance (facility location) or money
        const isCostAsDist = cost !== undefined && cost < 500 && volume !== undefined && volume > 10000;
        const costLabel = isCostAsDist ? "Distance" : "Cost";
        const costValue = isCostAsDist
          ? `${cost.toFixed(1)} miles`
          : `$${formatNumber(cost)}`;

        const html = `
          <div style="font-size:12px; min-width:200px">
            <div style="font-weight:700; font-size:13px; margin-bottom:6px; color:#1e293b">
              ${originName} <span style="color:#94a3b8">&rarr;</span> ${destName}
            </div>
            <div style="display:grid; grid-template-columns:auto 1fr; gap:2px 12px">
              ${volume !== undefined ? `
                <span style="color:#64748b">Volume</span>
                <span style="font-weight:600; text-align:right">${formatNumber(volume)} lbs</span>
              ` : ""}
              ${cost !== undefined ? `
                <span style="color:#64748b">${costLabel}</span>
                <span style="font-weight:600; text-align:right">${costValue}</span>
              ` : ""}
              ${!isCostAsDist && volume && cost ? `
                <span style="color:#64748b">Cost/1000 lbs</span>
                <span style="font-weight:600; text-align:right">$${(cost / volume * 1000).toFixed(2)}</span>
              ` : ""}
            </div>
          </div>
        `;
        layer.bindPopup(html, { maxWidth: 320, minWidth: 200 });

        // Hover effect
        layer.on({
          mouseover: (e) => {
            const target = e.target as L.Path;
            target.setStyle({
              weight: (target.options.weight ?? 3) + 2,
              opacity: 1,
            });
            target.bringToFront();
          },
          mouseout: (e) => {
            const target = e.target as L.Path;
            geoJsonLayer.resetStyle(target);
          },
        });

        // Collect endpoints with route info for summary popups
        const coords = (feature.geometry as GeoJSON.LineString).coordinates;
        if (coords.length >= 2) {
          const [oLon, oLat] = coords[0];
          const [dLon, dLat] = coords[coords.length - 1];
          const originKey = `o-${oLat.toFixed(4)},${oLon.toFixed(4)}`;
          const destKey = `d-${dLat.toFixed(4)},${dLon.toFixed(4)}`;

          if (!endpoints.has(originKey)) {
            endpoints.set(originKey, { lat: oLat, lon: oLon, type: "origin", name: originName, connections: [] });
          }
          endpoints.get(originKey)!.connections.push({
            name: destName, volume: volume ?? 0, distance: cost ?? 0,
          });

          if (!endpoints.has(destKey)) {
            endpoints.set(destKey, { lat: dLat, lon: dLon, type: "dest", name: destName, connections: [] });
          }
          endpoints.get(destKey)!.connections.push({
            name: originName, volume: volume ?? 0, distance: cost ?? 0,
          });
        }
      },
    });

    group.addLayer(geoJsonLayer);

    // Add endpoint markers with summary popups
    endpoints.forEach(({ lat, lon, type, name, connections }) => {
      const isOrigin = type === "origin";
      const color = isOrigin ? ORIGIN_COLOR : DEST_COLOR;

      // Determine entity label based on context
      const connCount = connections.length;
      const totalVol = connections.reduce((s, c) => s + c.volume, 0);
      const entityLabel = isOrigin
        ? (connCount === 1 ? "Cooperative" : `Cooperative (${connCount} routes)`)
        : (connCount === 1 ? "Facility" : `Facility (${connCount} connections)`);

      // Build connection summary table
      const sortedConns = [...connections].sort((a, b) => b.volume - a.volume);
      const connRows = sortedConns.slice(0, 8).map(c =>
        `<tr style="border-top:1px solid #f3f4f6">` +
        `<td style="padding:2px 6px 2px 0;color:#374151;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.name}</td>` +
        `<td style="padding:2px 4px;text-align:right;font-weight:500;white-space:nowrap">${formatNumber(c.volume)} lbs</td>` +
        `<td style="padding:2px 0 2px 4px;text-align:right;color:#6b7280;white-space:nowrap">${c.distance.toFixed(1)} mi</td>` +
        `</tr>`
      ).join("");
      const moreText = sortedConns.length > 8
        ? `<tr><td colspan="3" style="padding:4px 0 0;color:#94a3b8;font-size:11px">+${sortedConns.length - 8} more</td></tr>`
        : "";

      // Larger icon for hub nodes (many connections)
      const size = connCount > 3 ? 22 : 16;
      const icon = createLabeledIcon(color, name, size);

      const marker = L.marker([lat, lon], {
        icon,
        zIndexOffset: isOrigin ? 1000 : 1100,
      });
      marker.bindPopup(`
        <div style="font-size:12px; min-width:220px">
          <div style="font-weight:700; font-size:13px; margin-bottom:2px; color:#1e293b">${name}</div>
          <div style="color:#64748b; margin-bottom:4px">${entityLabel}</div>
          <div style="color:#374151; font-size:11px; margin-bottom:6px">
            Total: ${formatNumber(totalVol)} lbs &middot; ${lat.toFixed(4)}, ${lon.toFixed(4)}
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <thead>
              <tr style="border-bottom:1px solid #e5e7eb">
                <th style="text-align:left;padding:0 6px 2px 0;color:#9ca3af;font-weight:500">Connected To</th>
                <th style="text-align:right;padding:0 4px 2px;color:#9ca3af;font-weight:500">Volume</th>
                <th style="text-align:right;padding:0 0 2px 4px;color:#9ca3af;font-weight:500">Dist</th>
              </tr>
            </thead>
            <tbody>${connRows}${moreText}</tbody>
          </table>
        </div>
      `, { maxWidth: 360, minWidth: 220 });
      group.addLayer(marker);
    });

    group.addTo(map);
    layerGroupRef.current = group;

    return () => {
      if (layerGroupRef.current) {
        map.removeLayer(layerGroupRef.current);
        layerGroupRef.current = null;
      }
    };
  }, [routeGeoJson, layerVisibility.routes, map, minVol, maxVol]);

  return null; // Rendering handled imperatively via L.geoJSON
}
