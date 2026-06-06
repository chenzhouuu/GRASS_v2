"use client";

import { useEffect, useRef, useCallback } from "react";
import { useAppStore } from "@/stores/appStore";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useMapStore } from "@/stores/mapStore";
import {
  updateSessionPreferences,
  type SessionPreferences,
} from "@/lib/preferences";

const DEBOUNCE_MS = 1500;

/**
 * Watches databaseStore, appStore, and mapStore for changes
 * and debounces a PUT to /api/sessions/{id}/preferences.
 *
 * Mount once in AppShell / AppContent.
 */
export function usePreferencesSync() {
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const activeRightTab = useAppStore((s) => s.activeRightTab);

  const queryHistory = useDatabaseStore((s) => s.queryHistory);
  const savedQueries = useDatabaseStore((s) => s.savedQueries);

  const viewport = useMapStore((s) => s.viewport);
  const layerVisibility = useMapStore((s) => s.layerVisibility);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isInitialLoadRef = useRef(true);

  const save = useCallback(() => {
    const sessionId = useAppStore.getState().currentSessionId;
    if (!sessionId) return;

    const prefs: SessionPreferences = {
      query_history: useDatabaseStore.getState().queryHistory,
      saved_queries: useDatabaseStore.getState().savedQueries,
      active_right_tab: useAppStore.getState().activeRightTab,
      map_viewport: useMapStore.getState().viewport,
      layer_visibility: useMapStore.getState().layerVisibility,
    };

    void updateSessionPreferences(sessionId, prefs);
  }, []);

  // Debounced save whenever any tracked value changes
  useEffect(() => {
    // Skip the initial render (preferences are loaded from backend, not saved)
    if (isInitialLoadRef.current) {
      isInitialLoadRef.current = false;
      return;
    }

    if (!currentSessionId) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(save, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [
    currentSessionId,
    activeRightTab,
    queryHistory,
    savedQueries,
    viewport,
    layerVisibility,
    save,
  ]);

  // Reset the initial-load flag when session changes AND cancel any pending
  // save timer — otherwise a timer from the old session could fire and save
  // preferences to the wrong (new) session.
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    isInitialLoadRef.current = true;
  }, [currentSessionId]);
}
