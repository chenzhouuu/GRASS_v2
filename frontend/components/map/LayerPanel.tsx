"use client";

import { useState } from "react";
import { Layers, X, Eye, EyeOff } from "lucide-react";
import { useMapStore, type BuiltInLayer } from "@/stores/mapStore";
import { cn } from "@/lib/utils";

const LAYER_GROUPS = [
  {
    label: "Entities",
    layers: [
      { id: "markers" as BuiltInLayer, label: "Markers", color: "#16a34a" },
      { id: "clusters" as BuiltInLayer, label: "Clusters", color: "#2563eb" },
    ],
  },
  {
    label: "Flow",
    layers: [
      { id: "routes" as BuiltInLayer, label: "Supply Routes", color: "#d97706" },
    ],
  },
  {
    label: "Analysis",
    layers: [
      { id: "heatmap" as BuiltInLayer, label: "Heatmap", color: "#dc2626" },
    ],
  },
] as const;

export function LayerPanel() {
  const [open, setOpen] = useState(false);
  const layerVisibility = useMapStore((s) => s.layerVisibility);
  const toggleBuiltInLayer = useMapStore((s) => s.toggleBuiltInLayer);
  const markers = useMapStore((s) => s.markers);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="absolute top-3 left-3 z-[1000] flex items-center justify-center h-8 w-8 rounded-md bg-background border shadow-sm hover:bg-muted transition-colors"
        title="Manage layers"
      >
        <Layers className="h-4 w-4 text-foreground" />
      </button>
    );
  }

  return (
    <div className="absolute top-3 left-3 z-[1000] w-52 rounded-lg border bg-background shadow-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-medium">Layers</span>
        <button
          onClick={() => setOpen(false)}
          className="rounded p-0.5 hover:bg-muted transition-colors"
        >
          <X className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </div>

      {/* Layer groups */}
      <div className="p-2 space-y-2">
        {LAYER_GROUPS.map((group) => (
          <div key={group.label}>
            <p className="px-1 text-2xs font-semibold uppercase tracking-wider text-muted-foreground">
              {group.label}
            </p>
            <div className="mt-1 space-y-0.5">
              {group.layers.map((layer) => {
                const visible = layerVisibility[layer.id];
                return (
                  <button
                    key={layer.id}
                    onClick={() => toggleBuiltInLayer(layer.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                      visible ? "hover:bg-muted" : "opacity-50 hover:bg-muted"
                    )}
                  >
                    {visible ? (
                      <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <EyeOff className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: layer.color }}
                    />
                    <span className="flex-1 text-left">{layer.label}</span>
                    {layer.id === "markers" && markers.length > 0 && (
                      <span className="text-2xs text-muted-foreground">
                        {markers.length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
