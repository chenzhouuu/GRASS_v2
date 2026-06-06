"use client";

import { useCallback, useMemo, useState } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import html2canvas from "html2canvas";
import { useMapStore, type BuiltInLayer } from "@/stores/mapStore";
import { Button } from "@/components/ui/button";
import { Layers, Focus, Download, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Marker color config (shared with MapMarkers/MapClusters) ───────────────

const MARKER_LEGEND: { label: string; color: string }[] = [
  { label: "Farm / Producer", color: "#16a34a" },
  { label: "Company / Processor", color: "#2563eb" },
  { label: "Distributor", color: "#ea580c" },
  { label: "Warehouse", color: "#7c3aed" },
  { label: "Location", color: "#64748b" },
];

const ROUTE_LEGEND: { label: string; color: string }[] = [
  { label: "Low volume", color: "#22c55e" },
  { label: "Medium", color: "#eab308" },
  { label: "High volume", color: "#ef4444" },
];

const LAYER_CONFIG: { id: BuiltInLayer; label: string }[] = [
  { id: "markers", label: "Markers" },
  { id: "clusters", label: "Clusters" },
  { id: "routes", label: "Routes" },
  { id: "heatmap", label: "Heatmap" },
];

// ─── Focus on results ───────────────────────────────────────────────────────

function FocusButton() {
  const map = useMap();
  const markers = useMapStore((s) => s.markers);

  const handleFocus = useCallback(() => {
    if (markers.length === 0) return;
    const bounds = L.latLngBounds(
      markers.map((m) => [m.lat, m.lng] as [number, number])
    );
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
  }, [map, markers]);

  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={handleFocus}
      disabled={markers.length === 0}
      className="h-6 w-full justify-start gap-1.5 px-2 text-[11px]"
      title="Zoom to fit all markers"
    >
      <Focus className="h-3 w-3" />
      Focus on results
    </Button>
  );
}

// ─── Export PNG ──────────────────────────────────────────────────────────────

function ExportButton() {
  const map = useMap();
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const container = map.getContainer();
      const canvas = await html2canvas(container, {
        useCORS: true,
        allowTaint: true,
        logging: false,
      });
      const link = document.createElement("a");
      link.download = "map-export.png";
      link.href = canvas.toDataURL("image/png");
      link.click();
    } catch {
      // Export failed silently
    } finally {
      setExporting(false);
    }
  }, [map]);

  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={handleExport}
      disabled={exporting}
      className="h-6 w-full justify-start gap-1.5 px-2 text-[11px]"
      title="Export map as PNG"
    >
      <Download className={cn("h-3 w-3", exporting && "animate-pulse")} />
      {exporting ? "Exporting..." : "Export PNG"}
    </Button>
  );
}

// ─── Legend ──────────────────────────────────────────────────────────────────

function Legend() {
  const markers = useMapStore((s) => s.markers);
  const layers = useMapStore((s) => s.layers);

  // Determine which entity types are present
  const activeTypes = useMemo(() => {
    const types = new Set<string>();
    for (const m of markers) {
      if (m.type) types.add(m.type.toLowerCase());
    }
    return types;
  }, [markers]);

  const hasRoutes = layers.some((l) => l.type === "routes" && l.visible);

  const visibleMarkerLegend = MARKER_LEGEND.filter(({ label }) => {
    const terms = label.toLowerCase().split(/\s*\/\s*/);
    return terms.some((t) => activeTypes.has(t.trim()));
  });

  if (visibleMarkerLegend.length === 0 && !hasRoutes) return null;

  return (
    <div className="border-t border-border/50 px-2 py-1.5">
      <div className="mb-1 text-[10px] font-semibold text-muted-foreground">
        Legend
      </div>
      {visibleMarkerLegend.map(({ label, color }) => (
        <div key={label} className="flex items-center gap-1.5 py-0.5">
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: color }}
          />
          <span className="text-[10px] text-muted-foreground">{label}</span>
        </div>
      ))}
      {hasRoutes && (
        <>
          <div className="mt-1 mb-0.5 text-[10px] text-muted-foreground">
            Routes
          </div>
          {ROUTE_LEGEND.map(({ label, color }) => (
            <div key={label} className="flex items-center gap-1.5 py-0.5">
              <span
                className="inline-block h-0.5 w-3 shrink-0 rounded"
                style={{ backgroundColor: color }}
              />
              <span className="text-[10px] text-muted-foreground">{label}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// ─── Main controls panel ────────────────────────────────────────────────────

export function MapControls() {
  const layerVisibility = useMapStore((s) => s.layerVisibility);
  const toggleBuiltInLayer = useMapStore((s) => s.toggleBuiltInLayer);
  const [open, setOpen] = useState(false);

  return (
    <div className="absolute left-2 top-2 z-[1000]">
      {/* Toggle button */}
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setOpen(!open)}
        className="h-7 w-7 p-0 shadow-md"
        title="Layer controls"
      >
        <Layers className="h-3.5 w-3.5" />
      </Button>

      {/* Panel */}
      {open && (
        <div className="mt-1 w-44 rounded-md border bg-background/95 shadow-lg backdrop-blur-sm">
          {/* Layer checkboxes */}
          <div className="px-2 py-1.5">
            <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold text-muted-foreground">
              {open ? (
                <ChevronDown className="h-2.5 w-2.5" />
              ) : (
                <ChevronRight className="h-2.5 w-2.5" />
              )}
              Layers
            </div>
            {LAYER_CONFIG.map(({ id, label }) => (
              <label
                key={id}
                className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-muted/50"
              >
                <input
                  type="checkbox"
                  checked={layerVisibility[id]}
                  onChange={() => toggleBuiltInLayer(id)}
                  className="h-3 w-3 rounded border-border accent-primary"
                />
                {label}
              </label>
            ))}
          </div>

          {/* Actions */}
          <div className="border-t border-border/50 px-1 py-1">
            <FocusButton />
            <ExportButton />
          </div>

          {/* Auto-generated legend */}
          <Legend />
        </div>
      )}
    </div>
  );
}
