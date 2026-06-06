import { create } from "zustand";
import type { CypherResult, Neo4jSchema, SavedQuery } from "@/lib/types";

const MAX_HISTORY = 20;

interface DatabaseState {
  // ── Query editor ────────────────────────────────────────────────────────
  currentQuery: string;
  setQuery: (query: string) => void;

  // ── Results ─────────────────────────────────────────────────────────────
  results: CypherResult | null;
  isExecuting: boolean;
  setResults: (results: CypherResult | null) => void;
  setExecuting: (executing: boolean) => void;

  // ── History ─────────────────────────────────────────────────────────────
  queryHistory: CypherResult[];
  addToHistory: (entry: CypherResult) => void;
  clearHistory: () => void;

  // ── Saved queries ───────────────────────────────────────────────────────
  savedQueries: SavedQuery[];
  addSavedQuery: (query: SavedQuery) => void;
  removeSavedQuery: (id: string) => void;

  // ── Schema ──────────────────────────────────────────────────────────────
  schema: Neo4jSchema | null;
  schemaLoading: boolean;
  setSchema: (schema: Neo4jSchema | null) => void;
  setSchemaLoading: (loading: boolean) => void;
}

export const useDatabaseStore = create<DatabaseState>((set) => ({
  // Query editor
  currentQuery: "",
  setQuery: (query) => set({ currentQuery: query }),

  // Results
  results: null,
  isExecuting: false,
  setResults: (results) => set({ results }),
  setExecuting: (executing) => set({ isExecuting: executing }),

  // History (capped at MAX_HISTORY entries)
  queryHistory: [],
  addToHistory: (entry) =>
    set((s) => ({
      queryHistory: [entry, ...s.queryHistory].slice(0, MAX_HISTORY),
    })),
  clearHistory: () => set({ queryHistory: [] }),

  // Saved queries
  savedQueries: [],
  addSavedQuery: (query) =>
    set((s) => ({ savedQueries: [...s.savedQueries, query] })),
  removeSavedQuery: (id) =>
    set((s) => ({
      savedQueries: s.savedQueries.filter((q) => q.id !== id),
    })),

  // Schema
  schema: null,
  schemaLoading: false,
  setSchema: (schema) => set({ schema }),
  setSchemaLoading: (loading) => set({ schemaLoading: loading }),
}));
