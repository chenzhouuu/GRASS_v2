import { create } from "zustand";

export type HighlightSource = "map" | "table" | "chat" | null;

interface SelectionState {
  /** Entity IDs selected across panels */
  selectedEntityIds: string[];
  /** Entity currently hovered */
  hoveredEntityId: string | null;
  /** Which panel initiated the selection */
  highlightSource: HighlightSource;

  setSelected: (ids: string[], source: HighlightSource) => void;
  setHovered: (id: string | null, source: HighlightSource) => void;
  clearSelection: () => void;
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedEntityIds: [],
  hoveredEntityId: null,
  highlightSource: null,

  setSelected: (ids, source) =>
    set({ selectedEntityIds: ids, highlightSource: source }),

  setHovered: (id, source) =>
    set({ hoveredEntityId: id, highlightSource: source }),

  clearSelection: () =>
    set({ selectedEntityIds: [], hoveredEntityId: null, highlightSource: null }),
}));
