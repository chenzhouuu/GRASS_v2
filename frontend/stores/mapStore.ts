"use client";

import { create } from "zustand";
import type { MapMarker, MapLayer, MapViewport, GeoJSONFeatureCollection } from "@/lib/types";
import { getDefaultMapViewport } from "@/stores/settingsStore";

export type BuiltInLayer = "markers" | "clusters" | "routes" | "heatmap";

const DEFAULT_LAYER_VISIBILITY: Record<BuiltInLayer, boolean> = {
  markers: true,
  clusters: true,
  routes: true,
  heatmap: false,
};

interface MapState {
  // ── Markers ─────────────────────────────────────────────────────────────
  markers: MapMarker[];
  addMarkers: (markers: MapMarker[]) => void;
  replaceQueryResults: (markers: MapMarker[], layers?: MapLayer[]) => void;
  clearMarkers: () => void;
  removeMarker: (id: string) => void;

  // ── Layers ──────────────────────────────────────────────────────────────
  layers: MapLayer[];
  addLayer: (layer: MapLayer) => void;
  removeLayer: (id: string) => void;
  toggleLayerVisibility: (id: string) => void;
  clearLayers: () => void;

  // ── Built-in layer visibility ─────────────────────────────────────────
  layerVisibility: Record<BuiltInLayer, boolean>;
  toggleBuiltInLayer: (layer: BuiltInLayer) => void;

  // ── Viewport ────────────────────────────────────────────────────────────
  viewport: MapViewport;
  setViewport: (viewport: Partial<MapViewport>) => void;
  resetViewport: () => void;

  // ── Raw GeoJSON for native Leaflet rendering ──────────────────────────
  routeGeoJson: GeoJSONFeatureCollection | null;
  setRouteGeoJson: (geojson: GeoJSONFeatureCollection | null) => void;

  // ── Selection ───────────────────────────────────────────────────────────
  selectedMarkerId: string | null;
  setSelectedMarker: (id: string | null) => void;
  selectedRegionBbox: string | null;
  setSelectedRegionBbox: (bbox: string | null) => void;
  clearSelectedRegion: () => void;
}

export const useMapStore = create<MapState>((set) => ({
  // Markers
  markers: [],
  addMarkers: (markers) =>
    set((s) => {
      const existingIds = new Set(s.markers.map((m) => m.id));
      const newMarkers = markers.filter((m) => !existingIds.has(m.id));
      return { markers: [...s.markers, ...newMarkers] };
    }),
  replaceQueryResults: (markers, layers = []) =>
    set((s) => ({
      markers,
      layers,
      selectedMarkerId: s.selectedMarkerId && markers.some((m) => m.id === s.selectedMarkerId)
        ? s.selectedMarkerId
        : null,
    })),
  clearMarkers: () => set({ markers: [], selectedMarkerId: null }),
  removeMarker: (id) =>
    set((s) => ({
      markers: s.markers.filter((m) => m.id !== id),
      selectedMarkerId: s.selectedMarkerId === id ? null : s.selectedMarkerId,
    })),

  // Layers
  layers: [],
  addLayer: (layer) =>
    set((s) => {
      const exists = s.layers.some((l) => l.id === layer.id);
      if (exists) {
        return { layers: s.layers.map((l) => (l.id === layer.id ? layer : l)) };
      }
      return { layers: [...s.layers, layer] };
    }),
  removeLayer: (id) =>
    set((s) => ({ layers: s.layers.filter((l) => l.id !== id) })),
  toggleLayerVisibility: (id) =>
    set((s) => ({
      layers: s.layers.map((l) =>
        l.id === id ? { ...l, visible: !l.visible } : l,
      ),
    })),
  clearLayers: () => set({ layers: [] }),

  // Built-in layer visibility
  layerVisibility: { ...DEFAULT_LAYER_VISIBILITY },
  toggleBuiltInLayer: (layer) =>
    set((s) => ({
      layerVisibility: {
        ...s.layerVisibility,
        [layer]: !s.layerVisibility[layer],
      },
    })),

  // Viewport
  viewport: getDefaultMapViewport(),
  setViewport: (viewport) =>
    set((s) => ({ viewport: { ...s.viewport, ...viewport } })),
  resetViewport: () => set({ viewport: getDefaultMapViewport() }),

  // Raw GeoJSON
  routeGeoJson: null,
  setRouteGeoJson: (geojson) => set({ routeGeoJson: geojson }),

  // Selection
  selectedMarkerId: null,
  setSelectedMarker: (id) => set({ selectedMarkerId: id }),
  selectedRegionBbox: null,
  setSelectedRegionBbox: (bbox) => set({ selectedRegionBbox: bbox }),
  clearSelectedRegion: () => set({ selectedRegionBbox: null }),
}));
