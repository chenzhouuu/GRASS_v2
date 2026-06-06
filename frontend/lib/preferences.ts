import { apiUrl } from "@/lib/backend";
import type { CypherResult, SavedQuery, MapViewport } from "@/lib/types";
import { getDefaultMapViewport } from "@/stores/settingsStore";
import type { BuiltInLayer } from "@/stores/mapStore";

export interface SessionPreferences {
  query_history: CypherResult[];
  saved_queries: SavedQuery[];
  active_right_tab: string;
  map_viewport: MapViewport;
  layer_visibility: Record<BuiltInLayer, boolean>;
}

const DEFAULT_LAYER_VISIBILITY: Record<BuiltInLayer, boolean> = {
  markers: true,
  clusters: true,
  routes: true,
  heatmap: false,
};

function buildDefaultPreferences(): SessionPreferences {
  return {
    query_history: [],
    saved_queries: [],
    active_right_tab: "agent",
    map_viewport: getDefaultMapViewport(),
    layer_visibility: { ...DEFAULT_LAYER_VISIBILITY },
  };
}

export async function fetchSessionPreferences(
  sessionId: string,
): Promise<SessionPreferences> {
  const defaults = buildDefaultPreferences();

  try {
    const res = await fetch(apiUrl(`/api/sessions/${sessionId}/preferences`));
    if (!res.ok) return defaults;

    const data = (await res.json()) as Partial<SessionPreferences>;
    return {
      ...defaults,
      ...data,
      map_viewport: data.map_viewport
        ? { ...defaults.map_viewport, ...data.map_viewport }
        : defaults.map_viewport,
      layer_visibility: data.layer_visibility
        ? { ...defaults.layer_visibility, ...data.layer_visibility }
        : defaults.layer_visibility,
    };
  } catch {
    return defaults;
  }
}

export async function updateSessionPreferences(
  sessionId: string,
  prefs: SessionPreferences,
): Promise<void> {
  try {
    const res = await fetch(apiUrl(`/api/sessions/${sessionId}/preferences`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
    if (!res.ok) {
      console.warn(`[Preferences] Failed to save (${res.status}) for session ${sessionId}`);
    }
  } catch (err) {
    console.warn("[Preferences] Network error saving preferences:", err);
  }
}
