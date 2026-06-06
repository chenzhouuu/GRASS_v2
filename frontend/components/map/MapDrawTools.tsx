"use client";

import { useEffect, useRef, useCallback } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { useMapStore } from "@/stores/mapStore";

/**
 * Lightweight rectangle draw tool using native Leaflet events.
 * When `active` is true, clicking and dragging on the map draws
 * a rectangle. On mouseup, extracts the bounding box and sends
 * a spatial query to the chat.
 */
export function MapDrawTools({ active, onDone }: { active: boolean; onDone: () => void }) {
  const map = useMap();
  const rectRef = useRef<L.Rectangle | null>(null);
  const startRef = useRef<L.LatLng | null>(null);
  const drawingRef = useRef(false);
  const setSelectedRegionBbox = useMapStore((s) => s.setSelectedRegionBbox);

  const cleanup = useCallback(() => {
    // Remove any transient rectangle used while drawing.
    if (rectRef.current) {
      const rect = rectRef.current;
      if (map.hasLayer(rect)) {
        map.removeLayer(rect);
      }
    }
    rectRef.current = null;
    startRef.current = null;
    drawingRef.current = false;
  }, [map]);

  useEffect(() => {
    if (!active) return;

    // Change cursor
    const container = map.getContainer();
    container.style.cursor = "crosshair";

    // Disable map dragging while drawing
    map.dragging.disable();

    function onMouseDown(e: L.LeafletMouseEvent) {
      startRef.current = e.latlng;
      drawingRef.current = true;

      // Remove previous in-progress rectangle if any
      if (rectRef.current && map.hasLayer(rectRef.current)) {
        map.removeLayer(rectRef.current);
      }

      // Create initial rectangle
      const rect = L.rectangle(L.latLngBounds(e.latlng, e.latlng), {
        color: "#3b82f6",
        weight: 2,
        fillColor: "#3b82f6",
        fillOpacity: 0.15,
        dashArray: "6 3",
      }).addTo(map);
      rectRef.current = rect;
    }

    function onMouseMove(e: L.LeafletMouseEvent) {
      if (!drawingRef.current || !startRef.current || !rectRef.current) return;
      rectRef.current.setBounds(L.latLngBounds(startRef.current, e.latlng));
    }

    function onMouseUp(e: L.LeafletMouseEvent) {
      if (!drawingRef.current || !startRef.current) return;

      const bounds = L.latLngBounds(startRef.current, e.latlng);

      // Require a minimum size to avoid accidental clicks
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      const latDiff = Math.abs(ne.lat - sw.lat);
      const lngDiff = Math.abs(ne.lng - sw.lng);

      if (latDiff < 0.01 && lngDiff < 0.01) {
        // Too small — remove and ignore
        if (rectRef.current && map.hasLayer(rectRef.current)) {
          map.removeLayer(rectRef.current);
        }
        rectRef.current = null;
        startRef.current = null;
        drawingRef.current = false;
        return;
      }

      // Format bounding box
      const bbox = `${sw.lat.toFixed(4)},${sw.lng.toFixed(4)},${ne.lat.toFixed(4)},${ne.lng.toFixed(4)}`;

      // Re-enable map, reset cursor
      container.style.cursor = "";
      map.dragging.enable();

      // Persist region focus; all subsequent chat queries will include it.
      setSelectedRegionBbox(bbox);

      cleanup();
      onDone();
    }

    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);

    return () => {
      container.style.cursor = "";
      map.dragging.enable();
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("mouseup", onMouseUp);

      // Clean up any in-progress rectangle
      if (rectRef.current && map.hasLayer(rectRef.current)) {
        map.removeLayer(rectRef.current);
      }
      drawingRef.current = false;
      startRef.current = null;
    };
  }, [active, map, cleanup, onDone, setSelectedRegionBbox]);

  return null;
}
