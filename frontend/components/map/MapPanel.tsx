"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import {
  MapContainer,
  TileLayer,
  ZoomControl,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { MapInitRecovery } from "./MapInitRecovery";
import { MapMarkers } from "./MapMarkers";
import { MapClusters } from "./MapClusters";
import { MapRoutes } from "./MapRoutes";
import { MapRoutesGeoJSON } from "./MapRoutesGeoJSON";
import { MapControls } from "./MapControls";
import { MapDrawTools } from "./MapDrawTools";
import { MapFocusRegion } from "./MapFocusRegion";
import { LayerPanel } from "./LayerPanel";
import { Button } from "@/components/ui/button";
import { Maximize2, Minimize2, Crosshair, Trash2, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Tile URLs ──────────────────────────────────────────────────────────────

const MAP_TILE_CONFIGS = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  "carto-light": {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  },
  "carto-dark": {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  },
} as const;

// ─── Viewport sync component ───────────────────────────────────────────────

function ViewportSync() {
  const map = useMap();
  const viewport = useMapStore((s) => s.viewport);
  const setViewport = useMapStore((s) => s.setViewport);
  const lastViewportRef = useRef(viewport);

  // Sync store → map when viewport changes externally
  useEffect(() => {
    const prev = lastViewportRef.current;
    if (
      prev.center[0] !== viewport.center[0] ||
      prev.center[1] !== viewport.center[1] ||
      prev.zoom !== viewport.zoom
    ) {
      lastViewportRef.current = viewport;
      map.setView(viewport.center, viewport.zoom);
    }
  }, [map, viewport]);

  // Sync map → store when user pans/zooms
  useEffect(() => {
    function onMoveEnd() {
      const center = map.getCenter();
      const zoom = map.getZoom();
      const newViewport = {
        center: [center.lat, center.lng] as [number, number],
        zoom,
      };

      // Only update store if viewport actually changed (with tolerance for
      // floating-point drift from Leaflet's coordinate projection)
      const prev = lastViewportRef.current;
      const EPS = 1e-6;
      if (
        Math.abs(prev.center[0] - newViewport.center[0]) > EPS ||
        Math.abs(prev.center[1] - newViewport.center[1]) > EPS ||
        prev.zoom !== newViewport.zoom
      ) {
        lastViewportRef.current = newViewport;
        setViewport(newViewport);
      }
    }

    map.on("moveend", onMoveEnd);
    return () => {
      map.off("moveend", onMoveEnd);
    };
  }, [map, setViewport]);

  return null;
}

// ─── Auto-fit bounds when markers change ────────────────────────────────────

function AutoFitBounds() {
  const map = useMap();
  const markers = useMapStore((s) => s.markers);
  const prevCountRef = useRef(0);

  useEffect(() => {
    // Only auto-fit when markers are added (count increases)
    if (markers.length > 0 && markers.length !== prevCountRef.current) {
      const bounds = L.latLngBounds(
        markers.map((m) => [m.lat, m.lng] as [number, number])
      );
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    }
    prevCountRef.current = markers.length;
  }, [map, markers]);

  return null;
}

// ─── Map controls overlay ───────────────────────────────────────────────────

function MapToolbar({
  isFullscreen,
  onToggleFullscreen,
  isDrawing,
  onToggleDraw,
}: {
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  isDrawing: boolean;
  onToggleDraw: () => void;
}) {
  const markers = useMapStore((s) => s.markers);
  const clearMarkers = useMapStore((s) => s.clearMarkers);
  const resetViewport = useMapStore((s) => s.resetViewport);
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);
  const clearSelectedRegion = useMapStore((s) => s.clearSelectedRegion);

  return (
    <div className="absolute right-2 top-2 z-[1000] flex flex-col gap-1">
      <Button
        size="sm"
        variant="secondary"
        onClick={onToggleFullscreen}
        className="h-7 w-7 p-0 shadow-md"
        title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
      >
        {isFullscreen ? (
          <Minimize2 className="h-3.5 w-3.5" />
        ) : (
          <Maximize2 className="h-3.5 w-3.5" />
        )}
      </Button>

      <Button
        size="sm"
        variant={isDrawing ? "default" : "secondary"}
        onClick={onToggleDraw}
        className={cn("h-7 w-7 p-0 shadow-md", isDrawing && "bg-emerald-600 text-white hover:bg-emerald-700")}
        title={isDrawing ? "Cancel region select" : "Select region to analyze"}
      >
        <Square className="h-3.5 w-3.5" />
      </Button>

      <Button
        size="sm"
        variant="secondary"
        onClick={resetViewport}
        className="h-7 w-7 p-0 shadow-md"
        title="Reset view to default"
      >
        <Crosshair className="h-3.5 w-3.5" />
      </Button>

      {markers.length > 0 && (
        <Button
          size="sm"
          variant="secondary"
          onClick={clearMarkers}
          className="h-7 w-7 p-0 shadow-md"
          title="Clear all markers"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}

      {selectedRegionBbox && (
        <Button
          size="sm"
          variant="secondary"
          onClick={clearSelectedRegion}
          className="h-7 w-7 p-0 shadow-md"
          title="Clear region focus"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

// ─── Marker count badge ─────────────────────────────────────────────────────

function MarkerBadge() {
  const count = useMapStore((s) => s.markers.length);
  if (count === 0) return null;

  return (
    <div className="absolute bottom-2 left-2 z-[1000] rounded bg-background/90 px-2 py-1 text-[11px] text-muted-foreground shadow-md backdrop-blur-sm">
      {count} marker{count !== 1 ? "s" : ""}
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function MapPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isDrawing, setIsDrawing] = useState(false);
  const viewport = useMapStore((s) => s.viewport);
  const layerVisibility = useMapStore((s) => s.layerVisibility);
  const markerCount = useMapStore((s) => s.markers.length);
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);
  const mapSettings = useSettingsStore((s) => s.map);

  // Use clusters when enabled AND marker count exceeds threshold
  const useClusters = layerVisibility.clusters && markerCount > 20;
  const showMarkers = layerVisibility.markers && !useClusters;
  const showClusters = useClusters;
  const showRoutes = layerVisibility.routes;

  const tile = MAP_TILE_CONFIGS[mapSettings.tileProvider];

  const handleToggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setIsFullscreen(true));
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false));
    }
  }, []);

  const handleToggleDraw = useCallback(() => {
    setIsDrawing((prev) => !prev);
  }, []);

  const handleDrawDone = useCallback(() => {
    setIsDrawing(false);
  }, []);

  // Listen for external fullscreen changes (e.g. Escape key)
  useEffect(() => {
    function onFullscreenChange() {
      setIsFullscreen(!!document.fullscreenElement);
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <MapInitRecovery>
        <MapContainer
          center={viewport.center}
          zoom={viewport.zoom}
          zoomControl={false}
          className="h-full w-full"
          attributionControl={true}
        >
          <TileLayer
            key={mapSettings.tileProvider}
            attribution={tile.attribution}
            url={tile.url}
          />
          <ZoomControl position="bottomright" />
          <ViewportSync />
          <AutoFitBounds />
          {showMarkers && <MapMarkers />}
          {showClusters && <MapClusters />}
          {showRoutes && <MapRoutes />}
          {showRoutes && <MapRoutesGeoJSON />}
          <MapFocusRegion />
          <MapControls />
          <MapDrawTools active={isDrawing} onDone={handleDrawDone} />
        </MapContainer>
      </MapInitRecovery>

      <LayerPanel />
      <MapToolbar
        isFullscreen={isFullscreen}
        onToggleFullscreen={handleToggleFullscreen}
        isDrawing={isDrawing}
        onToggleDraw={handleToggleDraw}
      />
      {isDrawing && (
        <div className="absolute left-1/2 top-2 z-[1000] -translate-x-1/2 rounded bg-emerald-600 px-3 py-1 text-xs text-white shadow-md">
          Click and drag to select a region
        </div>
      )}
      {!isDrawing && selectedRegionBbox && (
        <div className="absolute left-1/2 top-2 z-[1000] -translate-x-1/2 rounded bg-emerald-600 px-3 py-1 text-xs text-white shadow-md">
          Region focus active
        </div>
      )}
      <MarkerBadge />
    </div>
  );
}
