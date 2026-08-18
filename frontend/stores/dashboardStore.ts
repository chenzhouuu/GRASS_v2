"use client";

import { create } from "zustand";
import {
  executeDashboardCard,
  fetchDashboardCatalog,
  fetchDashboardContext,
  fetchDashboardSchema,
} from "@/lib/dashboardApi";
import type {
  DashboardCardDefinition,
  DashboardCardResult,
  DashboardCatalog,
  DashboardContext,
  DatabaseSchemaOverview,
} from "@/lib/types";

const MAX_CONCURRENT = 3;

interface DashboardState {
  context: DashboardContext | null;
  catalog: DashboardCatalog | null;
  cardResults: Record<string, DashboardCardResult>;
  schema: DatabaseSchemaOverview | null;
  loadingContext: boolean;
  loadingCatalog: boolean;
  loadingSchema: boolean;
  executingCards: Set<string>;
  error: string | null;
  lastLoadedAt: number | null;
  lastFingerprint: string | null;
  /** Incremented on every (re)load; async writers bail out if it changed. */
  loadGeneration: number;

  loadDashboard: () => Promise<void>;
  refreshDashboard: () => Promise<void>;
  executeCard: (card: DashboardCardDefinition) => Promise<void>;
  executeOperationalCards: () => Promise<void>;
  loadSchema: () => Promise<void>;
  invalidateIfStale: (fingerprint: string) => void;
}

function resetDashboardState(): Partial<DashboardState> {
  return {
    context: null,
    catalog: null,
    cardResults: {},
    schema: null,
    loadingContext: false,
    loadingCatalog: false,
    executingCards: new Set(),
    error: null,
    lastLoadedAt: null,
  };
}

export const useDashboardStore = create<DashboardState>((set, get) => ({
  context: null,
  catalog: null,
  cardResults: {},
  schema: null,
  loadingContext: false,
  loadingCatalog: false,
  loadingSchema: false,
  executingCards: new Set(),
  error: null,
  lastLoadedAt: null,
  lastFingerprint: null,
  loadGeneration: 0,

  loadDashboard: async () => {
    if (get().loadingContext || get().loadingCatalog) return;
    const gen = get().loadGeneration + 1;
    set({ loadGeneration: gen, loadingContext: true, loadingCatalog: true, error: null });
    try {
      const context = await fetchDashboardContext();
      if (get().loadGeneration !== gen) return;
      set({
        context,
        loadingContext: false,
        lastFingerprint: context.fingerprint,
      });
      if (!context.connection.connected) {
        set({
          catalog: null,
          loadingCatalog: false,
          lastLoadedAt: Date.now(),
        });
        return;
      }
      const catalog = await fetchDashboardCatalog();
      if (get().loadGeneration !== gen) return;
      set({
        catalog,
        loadingCatalog: false,
        lastLoadedAt: Date.now(),
      });
      await get().executeOperationalCards();
    } catch (error) {
      if (get().loadGeneration !== gen) return;
      set({
        loadingContext: false,
        loadingCatalog: false,
        error: error instanceof Error ? error.message : "Failed to load dashboard",
      });
    }
  },

  refreshDashboard: async () => {
    set((state) => ({
      ...resetDashboardState(),
      loadGeneration: state.loadGeneration + 1,
    }));
    await get().loadDashboard();
  },

  executeCard: async (card) => {
    const { context, catalog, executingCards, cardResults } = get();
    if (!context || !catalog || !card.cypher) return;
    if (executingCards.has(card.id) || cardResults[card.id]?.status === "success") return;

    const gen = get().loadGeneration;
    const nextExecuting = new Set(executingCards);
    nextExecuting.add(card.id);
    set({ executingCards: nextExecuting });

    try {
      const result = await executeDashboardCard({
        cardId: card.id,
        cypher: card.cypher,
        fingerprint: catalog.fingerprint,
        timeoutMs: card.timeoutMs,
      });
      if (get().loadGeneration !== gen) return;
      const updatedExecuting = new Set(get().executingCards);
      updatedExecuting.delete(card.id);
      set({
        executingCards: updatedExecuting,
        cardResults: { ...get().cardResults, [card.id]: result },
      });
    } catch (error) {
      if (get().loadGeneration !== gen) return;
      const updatedExecuting = new Set(get().executingCards);
      updatedExecuting.delete(card.id);
      set({
        executingCards: updatedExecuting,
        cardResults: {
          ...get().cardResults,
          [card.id]: {
            cardId: card.id,
            status: "error",
            executionMs: 0,
            error: error instanceof Error ? error.message : "Failed to execute card",
          },
        },
      });
    }
  },

  executeOperationalCards: async () => {
    const { catalog } = get();
    if (!catalog) return;
    const operational = catalog.cards.filter((card) => card.layer === "operational" && card.cypher);
    let index = 0;

    async function worker() {
      while (index < operational.length) {
        const current = operational[index];
        index += 1;
        await get().executeCard(current);
      }
    }

    await Promise.all(
      Array.from({ length: Math.min(MAX_CONCURRENT, operational.length) }, () => worker()),
    );
  },

  loadSchema: async () => {
    if (get().loadingSchema || get().schema) return;
    set({ loadingSchema: true });
    try {
      const schema = await fetchDashboardSchema();
      set({ schema, loadingSchema: false });
    } catch (error) {
      set({
        loadingSchema: false,
        error: error instanceof Error ? error.message : "Failed to load schema",
      });
    }
  },

  invalidateIfStale: (fingerprint) => {
    const { lastFingerprint } = get();
    if (lastFingerprint && lastFingerprint !== fingerprint) {
      void get().refreshDashboard();
    }
  },
}));
