import { create } from "zustand";
import type { Session } from "@/lib/types";

export type RightPanelTab = "agent" | "map" | "data" | "charts";

interface TabBadge {
  type: "new" | "updated" | null;
}

interface AppState {
  // ── Right panel ─────────────────────────────────────────────────────────
  activeRightTab: RightPanelTab;
  setActiveRightTab: (tab: RightPanelTab) => void;
  tabBadges: Record<RightPanelTab, TabBadge>;
  setTabBadge: (tab: RightPanelTab, badge: TabBadge) => void;
  clearTabBadge: (tab: RightPanelTab) => void;

  // ── Auto-switch ───────────────────────────────────────────────────────
  autoSwitchEnabled: boolean;
  setAutoSwitchEnabled: (enabled: boolean) => void;
  lastPanelInteraction: number; // timestamp of last user interaction with right panel
  recordPanelInteraction: () => void;
  /** Auto-switch to tab if user is idle (>3s since last interaction) */
  autoSwitchTab: (tab: RightPanelTab) => void;

  // ── Sidebar ─────────────────────────────────────────────────────────────
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;

  // ── Sessions ────────────────────────────────────────────────────────────
  sessions: Session[];
  currentSessionId: string | null;
  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (id: string | null) => void;
  addSession: (session: Session) => void;
  removeSession: (id: string) => void;
  updateSession: (id: string, patch: Partial<Session>) => void;

  // ── Report ─────────────────────────────────────────────────────────────
  reportUrl: string | null;
  reportTitle: string | null;
  setReport: (url: string | null, title?: string | null) => void;

  // ── Neo4j connection status ─────────────────────────────────────────────
  neo4jConnected: boolean;
  setNeo4jConnected: (connected: boolean) => void;
}

const emptyBadge: TabBadge = { type: null };

export const useAppStore = create<AppState>((set, get) => ({
  // Right panel
  activeRightTab: "agent",
  setActiveRightTab: (tab) => {
    set({ activeRightTab: tab, tabBadges: { ...get().tabBadges, [tab]: emptyBadge } });
  },
  tabBadges: {
    agent: { type: null },
    map: { type: null },
    data: { type: null },
    charts: { type: null },
  },
  setTabBadge: (tab, badge) =>
    set((s) => ({ tabBadges: { ...s.tabBadges, [tab]: badge } })),
  clearTabBadge: (tab) =>
    set((s) => ({ tabBadges: { ...s.tabBadges, [tab]: emptyBadge } })),

  // Auto-switch
  autoSwitchEnabled: true,
  setAutoSwitchEnabled: (enabled) => set({ autoSwitchEnabled: enabled }),
  lastPanelInteraction: 0,
  recordPanelInteraction: () => set({ lastPanelInteraction: Date.now() }),
  autoSwitchTab: (tab) => {
    const state = get();
    if (!state.autoSwitchEnabled) {
      // Badge instead of switch
      set((s) => ({ tabBadges: { ...s.tabBadges, [tab]: { type: "new" } } }));
      return;
    }
    const idle = Date.now() - state.lastPanelInteraction > 3000;
    if (idle) {
      set({ activeRightTab: tab, tabBadges: { ...state.tabBadges, [tab]: emptyBadge } });
    } else {
      // User is active — badge only
      set((s) => ({ tabBadges: { ...s.tabBadges, [tab]: { type: "new" } } }));
    }
  },

  // Sidebar
  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  // Sessions
  sessions: [],
  currentSessionId: null,
  setSessions: (sessions) => set({ sessions }),
  setCurrentSession: (id) => set({ currentSessionId: id }),
  addSession: (session) =>
    set((s) => ({ sessions: [session, ...s.sessions] })),
  removeSession: (id) =>
    set((s) => ({
      sessions: s.sessions.filter((sess) => sess.id !== id),
      currentSessionId: s.currentSessionId === id ? null : s.currentSessionId,
    })),
  updateSession: (id, patch) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === id ? { ...sess, ...patch } : sess
      ),
    })),

  // Report
  reportUrl: null,
  reportTitle: null,
  setReport: (url, title = null) => set({ reportUrl: url, reportTitle: title }),

  // Neo4j
  neo4jConnected: false,
  setNeo4jConnected: (connected) => set({ neo4jConnected: connected }),
}));
