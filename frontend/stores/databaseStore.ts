import { create } from "zustand";
import type {
  CypherResult,
  DatabaseResultsViewMode,
  Neo4jSchema,
  SavedQuery,
} from "@/lib/types";

const MAX_HISTORY = 20;

function hasGraphData(results: CypherResult | null) {
  const graph = results?.graph;
  return !!graph && (graph.nodes.length > 0 || graph.relationships.length > 0);
}

interface DatabaseState {
  // ── Query editor ────────────────────────────────────────────────────────
  currentQuery: string;
  setQuery: (query: string) => void;

  // ── Results ─────────────────────────────────────────────────────────────
  results: CypherResult | null;
  resultsViewMode: DatabaseResultsViewMode;
  resultsViewModeTouched: boolean;
  isExecuting: boolean;
  setResults: (results: CypherResult | null) => void;
  setResultsViewMode: (mode: DatabaseResultsViewMode) => void;
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
  resultsViewMode: "table",
  resultsViewModeTouched: false,
  isExecuting: false,
  setResults: (results) =>
    set((state) => {
      if (results === null) {
        return {
          results,
          resultsViewMode: "table",
          resultsViewModeTouched: false,
        };
      }
      const autoMode = hasGraphData(results) ? "graph" : "table";
      const requestedMode =
        state.resultsViewMode === "graph" && !hasGraphData(results)
          ? "table"
          : state.resultsViewMode;
      return {
        results,
        resultsViewMode: state.resultsViewModeTouched ? requestedMode : autoMode,
      };
    }),
  setResultsViewMode: (mode) =>
    set({ resultsViewMode: mode, resultsViewModeTouched: true }),
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
