"use client";

import { useEffect } from "react";
import { useAppStore, type RightPanelTab } from "@/stores/appStore";

const TAB_MAP: Record<string, RightPanelTab> = {
  "1": "agent",
  "2": "map",
  "3": "data",
  "4": "charts",
};

export function useKeyboardShortcuts({
  onSearch,
  onHelp,
}: {
  onSearch: () => void;
  onHelp: () => void;
}) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;

      // Cmd+K — focus search
      if (e.key === "k") {
        e.preventDefault();
        onSearch();
        return;
      }

      // Cmd+/ — help
      if (e.key === "/") {
        e.preventDefault();
        onHelp();
        return;
      }

      // Cmd+1-4 — switch right panel tab
      const tab = TAB_MAP[e.key];
      if (tab) {
        e.preventDefault();
        useAppStore.getState().setActiveRightTab(tab);
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onSearch, onHelp]);
}
