"use client";

import { useEffect, useCallback, useRef, useState } from "react";
import { useAppStore } from "@/stores/appStore";
import { useChatStore } from "@/stores/chatStore";
import { useAgentStore } from "@/stores/agentStore";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useMapStore } from "@/stores/mapStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { getDemoData } from "@/lib/demoData";
import { fetchSessionPreferences } from "@/lib/preferences";
import { reconnectToActiveRun } from "@/lib/api";
import { stopRunWatch } from "@/lib/runWatch";
import { apiUrl } from "@/lib/backend";
import { geoJsonToMapPayload } from "@/lib/mapData";
import type { Message, Session } from "@/lib/types";

const API = apiUrl("/api/sessions");
const ACTIVE_SESSION_STORAGE_KEY = "grass.currentSessionId";

// ─── Map snake_case API response to camelCase frontend Session ──────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mapSession(raw: any): Session {
  return {
    id: raw.id,
    title: raw.title,
    createdAt: raw.created_at ?? raw.createdAt ?? 0,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? 0,
    messageCount: raw.message_count ?? raw.messageCount ?? 0,
    lastMessagePreview: raw.last_message_preview ?? raw.lastMessagePreview,
  };
}

interface SessionDetail {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  last_message_preview?: string;
  messages: Array<{
    id: number;
    role: Message["role"];
    content: string;
    timestamp: number;
    metadata?: {
      visualizations?: Message["visualizations"];
      geo_data?: Record<string, unknown>;
    } | null;
  }>;
}

function mapStoredMessage(raw: SessionDetail["messages"][number]): Message {
  const msg: Message = {
    id: String(raw.id),
    role: raw.role,
    content: raw.content,
    timestamp: raw.timestamp,
  };

  // Hydrate rich metadata (visualizations, map data) from backend persistence
  if (raw.metadata) {
    if (raw.metadata.visualizations?.length) {
      msg.visualizations = raw.metadata.visualizations;
    }
    if (raw.metadata.geo_data) {
      const geoJson = raw.metadata.geo_data as unknown as import("@/lib/types").GeoJSONFeatureCollection;
      msg.mapData = geoJsonToMapPayload(geoJson);
      // Preserve raw GeoJSON for native Leaflet rendering (OSRM road geometry)
      (msg as unknown as Record<string, unknown>)._rawGeoJson = geoJson;
    }
  }

  return msg;
}

// ─── Fetch all sessions ──────────────────────────────────────────────────────

async function fetchSessionsFromApi(): Promise<Session[]> {
  const res = await fetch(API);
  if (!res.ok) throw new Error(`Failed to fetch sessions (${res.status})`);
  const data = await res.json();
  return (data as unknown[]).map(mapSession);
}

async function fetchSessionDetailFromApi(sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`${API}/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch session detail (${res.status})`);
  }
  return (await res.json()) as SessionDetail;
}

function persistCurrentSessionId(sessionId: string | null) {
  if (typeof window === "undefined") return;
  if (sessionId) {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  } else {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  }
}

function getPersistedCurrentSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
}

function resetSessionStores() {
  // Stop WATCHING any in-flight run — deliberately not stopping the run
  // itself: the backend owns it and will finish and persist regardless.
  stopRunWatch();
  useChatStore.getState().clearMessages();
  useChatStore.getState().setPendingPlan(null);
  useChatStore.getState().setStreaming(false, null);
  useAgentStore.getState().reset();

  const db = useDatabaseStore.getState();
  db.setQuery("");
  db.setResults(null);
  db.clearHistory();

  const map = useMapStore.getState();
  map.clearMarkers();
  map.clearLayers();
  map.clearSelectedRegion();
  map.resetViewport();

  useAppStore.getState().setReport(null);
}

function loadDemoSession(id: string): boolean {
  const demo = getDemoData(id);
  if (!demo) return false;

  for (const msg of demo.messages) {
    useChatStore.getState().addMessage(msg);
  }

  useAgentStore.setState((s) => ({
    livePipeline: null,
    pipelineHistory: {
      ...s.pipelineHistory,
      [demo.pipeline.messageId]: demo.pipeline,
    },
  }));

  const db = useDatabaseStore.getState();
  db.setQuery(demo.cypherResult.query);
  db.setResults(demo.cypherResult);
  return true;
}

export async function refreshSessionsStore(): Promise<Session[]> {
  const sessions = await fetchSessionsFromApi();
  useAppStore.getState().setSessions(sessions);
  return sessions;
}

export async function loadSessionIntoStores(sessionId: string): Promise<void> {
  useAppStore.getState().setCurrentSession(sessionId);
  persistCurrentSessionId(sessionId);
  resetSessionStores();

  if (loadDemoSession(sessionId)) {
    useSettingsStore.getState().resetSessionModelConfig();
    return;
  }

  await useSettingsStore.getState().loadSessionModelConfig(sessionId);
  const detail = await fetchSessionDetailFromApi(sessionId);
  if (useAppStore.getState().currentSessionId !== sessionId) {
    return;
  }
  let latestMapData: Message["mapData"] | undefined;
  let latestRawGeoJson: import("@/lib/types").GeoJSONFeatureCollection | null = null;
  for (const message of detail.messages.map(mapStoredMessage)) {
    useChatStore.getState().addMessage(message);
    if (message.mapData) {
      latestMapData = message.mapData;
    }
    // Retrieve preserved raw GeoJSON for native route rendering
    const rawGeo = (message as unknown as Record<string, unknown>)._rawGeoJson as
      import("@/lib/types").GeoJSONFeatureCollection | undefined;
    if (rawGeo?.features?.length) {
      latestRawGeoJson = rawGeo;
    }
  }

  if (latestMapData) {
    const hasLineStrings = latestRawGeoJson?.features?.some(
      (f) => f.geometry?.type === "LineString"
    );
    if (hasLineStrings && latestRawGeoJson) {
      // Restore native GeoJSON route rendering (OSRM road geometry)
      useMapStore.getState().setRouteGeoJson(latestRawGeoJson);
      useMapStore.getState().replaceQueryResults(latestMapData.markers ?? [], []);
    } else {
      useMapStore.getState().setRouteGeoJson(null);
      useMapStore.getState().replaceQueryResults(
        latestMapData.markers ?? [],
        latestMapData.layers ?? [],
      );
    }
  }

  // If this session has a run in flight (refresh, second tab, switching
  // back), re-attach to it — the replayed backlog rebuilds the live view.
  void reconnectToActiveRun(sessionId).catch(() => undefined);

  // Restore per-session UI preferences (query history, saved queries, tab, map state)
  try {
    const prefs = await fetchSessionPreferences(sessionId);
    if (useAppStore.getState().currentSessionId !== sessionId) return;

    // Database panel
    const db = useDatabaseStore.getState();
    for (const entry of prefs.query_history) {
      db.addToHistory(entry as import("@/lib/types").CypherResult);
    }
    for (const sq of prefs.saved_queries) {
      db.addSavedQuery(sq as import("@/lib/types").SavedQuery);
    }

    // Right panel tab
    useAppStore
      .getState()
      .setActiveRightTab(
        prefs.active_right_tab as import("@/stores/appStore").RightPanelTab,
      );

    // Map viewport and layer visibility
    const map = useMapStore.getState();
    if (prefs.map_viewport) {
      map.setViewport(prefs.map_viewport);
    }
    if (prefs.layer_visibility) {
      // Apply each layer visibility setting
      const currentVis = map.layerVisibility;
      for (const [layer, visible] of Object.entries(prefs.layer_visibility)) {
        if (currentVis[layer as import("@/stores/mapStore").BuiltInLayer] !== visible) {
          map.toggleBuiltInLayer(layer as import("@/stores/mapStore").BuiltInLayer);
        }
      }
    }
  } catch {
    // Preferences are non-critical — silently use defaults
  }
}

// ─── CRUD helpers (called outside React lifecycle too) ───────────────────────

export async function createSession(title?: string): Promise<Session> {
  const settingsState = useSettingsStore.getState();
  const draftAgentModels = settingsState.agentModels;
  const draftApiKeys = settingsState.providerApiKeys;
  // Carry config to new session if dirty OR if user has non-default config
  // (e.g., user already "Applied" to a previous session — dirty is false,
  // but the config still needs to be pushed to the new session)
  const shouldPushConfig =
    settingsState.modelConfigDirty || settingsState.hasNonDefaultModelConfig();

  const res = await fetch(API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title ?? "New Session" }),
  });
  if (!res.ok) throw new Error(`Failed to create session (${res.status})`);
  const session = mapSession(await res.json());
  useAppStore.getState().addSession(session);
  useAppStore.getState().setCurrentSession(session.id);
  persistCurrentSessionId(session.id);
  await useSettingsStore.getState().loadSessionModelConfig(session.id);
  if (shouldPushConfig) {
    useSettingsStore.getState().applySessionModelConfig(
      draftAgentModels,
      draftApiKeys,
      true,
    );
    await useSettingsStore.getState().saveSessionModelConfig(session.id);
  }
  return session;
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API}/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete session (${res.status})`);
  useAppStore.getState().removeSession(id);
  if (useAppStore.getState().currentSessionId === null) {
    resetSessionStores();
    persistCurrentSessionId(null);
    useSettingsStore.getState().resetSessionModelConfig();
  }
}

export async function renameSession(
  id: string,
  title: string,
): Promise<void> {
  const res = await fetch(`${API}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Failed to rename session (${res.status})`);
  useAppStore.getState().updateSession(id, { title });
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useSessions() {
  const sessions = useAppStore((s) => s.sessions);
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const setSessions = useAppStore((s) => s.setSessions);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const restoredSelectionRef = useRef(false);

  // Fetch on mount
  useEffect(() => {
    refreshSessionsStore()
      .then(setSessions)
      .catch(() => {
        /* silent — mock API might not be ready */
      })
      .finally(() => {
        setSessionsLoaded(true);
      });
  }, [setSessions]);

  useEffect(() => {
    persistCurrentSessionId(currentSessionId);
  }, [currentSessionId]);

  // Switching away during a run is allowed: it only stops WATCHING (the
  // backend finishes the run), and selecting the session again re-attaches.
  const handleNew = useCallback(async () => {
    const session = await createSession();
    resetSessionStores();
    persistCurrentSessionId(session.id);
  }, []);

  const handleSelect = useCallback(async (id: string) => {
    await loadSessionIntoStores(id);
  }, []);

  useEffect(() => {
    if (!sessionsLoaded || restoredSelectionRef.current || currentSessionId) return;
    restoredSelectionRef.current = true;
    const persistedSessionId = getPersistedCurrentSessionId();
    if (!persistedSessionId) return;
    if (sessions.some((session) => session.id === persistedSessionId)) {
      void handleSelect(persistedSessionId);
    }
  }, [sessionsLoaded, currentSessionId, sessions, handleSelect]);

  return {
    sessions,
    currentSessionId,
    createSession: handleNew,
    selectSession: handleSelect,
    deleteSession,
    renameSession,
  };
}
