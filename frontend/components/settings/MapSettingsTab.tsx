"use client";

import { Input } from "@/components/ui/input";
import { useMapStore } from "@/stores/mapStore";
import { useSettingsStore, type MapConfig } from "@/stores/settingsStore";
import { MapConfigValidator } from "@/lib/validators";
import { cn } from "@/lib/utils";

const TILE_PROVIDERS: { value: MapConfig["tileProvider"]; label: string; desc: string }[] = [
  { value: "osm", label: "OpenStreetMap", desc: "Standard map tiles" },
  { value: "carto-light", label: "CartoDB Positron", desc: "Light minimal style" },
  { value: "carto-dark", label: "CartoDB Dark Matter", desc: "Dark background" },
];

function FormField({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-2xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

export function MapSettingsTab() {
  const map = useSettingsStore((s) => s.map);
  const setMapConfig = useSettingsStore((s) => s.setMapConfig);
  const viewport = useMapStore((s) => s.viewport);
  const setViewport = useMapStore((s) => s.setViewport);
  const markerCount = useMapStore((s) => s.markers.length);
  const layerCount = useMapStore((s) => s.layers.length);
  const routeGeoJson = useMapStore((s) => s.routeGeoJson);
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);

  function updateMapConfig(patch: Partial<MapConfig>) {
    const nextMap = { ...map, ...patch };
    const viewportMatchesCurrentDefaults =
      viewport.center[0] === map.center[0] &&
      viewport.center[1] === map.center[1] &&
      viewport.zoom === map.zoom;
    const hasActiveMapData =
      markerCount > 0 ||
      layerCount > 0 ||
      !!routeGeoJson ||
      !!selectedRegionBbox;

    setMapConfig(patch);

    if (!hasActiveMapData && viewportMatchesCurrentDefaults) {
      setViewport({ center: nextMap.center, zoom: nextMap.zoom });
    }
  }

  return (
    <div className="space-y-8">
      {/* ── Default viewport ─────────────────────────────────────── */}
      <div className="space-y-4">
        <div>
          <h3 className="text-[14px] font-semibold">Default viewport</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Initial map center and zoom level when no data is loaded.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <FormField label="Latitude" htmlFor="map-lat" hint="-90 to 90">
            <Input
              id="map-lat"
              type="number"
              step="0.0001"
              value={map.center[0]}
              onChange={(e) =>
                updateMapConfig({
                  center: [MapConfigValidator.latitude(parseFloat(e.target.value)), map.center[1]],
                })
              }
              className="h-8 text-sm"
            />
          </FormField>

          <FormField label="Longitude" htmlFor="map-lng" hint="-180 to 180">
            <Input
              id="map-lng"
              type="number"
              step="0.0001"
              value={map.center[1]}
              onChange={(e) =>
                updateMapConfig({
                  center: [map.center[0], MapConfigValidator.longitude(parseFloat(e.target.value))],
                })
              }
              className="h-8 text-sm"
            />
          </FormField>

          <FormField label="Zoom" htmlFor="map-zoom" hint="1 to 18">
            <Input
              id="map-zoom"
              type="number"
              min={1}
              max={18}
              value={map.zoom}
              onChange={(e) =>
                updateMapConfig({
                  zoom: MapConfigValidator.zoom(parseInt(e.target.value, 10)),
                })
              }
              className="h-8 text-sm"
            />
          </FormField>
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* ── Tile provider ────────────────────────────────────────── */}
      <div className="space-y-4">
        <div>
          <h3 className="text-[14px] font-semibold">Map style</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Choose the base map tile provider for the map panel.
          </p>
        </div>

        <div className="flex gap-2.5">
          {TILE_PROVIDERS.map((tp) => (
            <button
              key={tp.value}
              type="button"
              onClick={() => updateMapConfig({ tileProvider: tp.value })}
              className={cn(
                "flex flex-1 flex-col items-center gap-2 rounded-xl border-2 p-4 text-center transition-all",
                map.tileProvider === tp.value
                  ? "border-primary bg-accent-subtle text-primary"
                  : "border-transparent bg-muted/40 text-muted-foreground hover:border-border hover:bg-muted/60"
              )}
            >
              <div className={cn(
                "h-10 w-full rounded-md",
                tp.value === "osm" && "bg-[#dde6d5]",
                tp.value === "carto-light" && "bg-[#e8e0d8]",
                tp.value === "carto-dark" && "bg-[#2b2b2b]",
              )} />
              <div>
                <p className="text-sm font-medium">{tp.label}</p>
                <p className="mt-0.5 text-2xs opacity-70">{tp.desc}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
