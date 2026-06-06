"use client";

import { useCallback } from "react";
import dynamic from "next/dynamic";
import { Workflow, Map, Database, BarChart3 } from "lucide-react";
import { useAppStore, type RightPanelTab } from "@/stores/appStore";
import { PanelErrorBoundary } from "./ErrorBoundary";
import { ContextBanner } from "./ContextBanner";
import {
  AgentSkeleton,
  MapSkeleton,
  DatabaseSkeleton,
  ChartSkeleton,
} from "./Skeletons";
import { cn } from "@/lib/utils";

const AgentPanel = dynamic(
  () => import("@/components/agent/AgentPanel").then((m) => m.AgentPanel),
  { ssr: false, loading: () => <AgentSkeleton /> }
);

const DatabasePanel = dynamic(
  () => import("@/components/database/DatabasePanel").then((m) => m.DatabasePanel),
  { ssr: false, loading: () => <DatabaseSkeleton /> }
);

const MapPanel = dynamic(
  () => import("@/components/map/MapPanel").then((m) => m.MapPanel),
  { ssr: false, loading: () => <MapSkeleton /> }
);

const ChartGallery = dynamic(
  () => import("@/components/visualization/ChartGallery").then((m) => m.ChartGallery),
  { ssr: false, loading: () => <ChartSkeleton /> }
);

const tabs: { value: RightPanelTab; label: string; icon: React.ElementType }[] = [
  { value: "agent", label: "Agent", icon: Workflow },
  { value: "map", label: "Map", icon: Map },
  { value: "data", label: "Data", icon: Database },
  { value: "charts", label: "Charts", icon: BarChart3 },
];

/** Tab pane — always mounted, hidden when inactive via CSS */
function TabPane({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "absolute inset-0",
        active ? "visible z-10" : "invisible z-0"
      )}
    >
      {children}
    </div>
  );
}

export function RightPanel() {
  const activeTab = useAppStore((s) => s.activeRightTab);
  const setActiveTab = useAppStore((s) => s.setActiveRightTab);
  const tabBadges = useAppStore((s) => s.tabBadges);
  const recordPanelInteraction = useAppStore((s) => s.recordPanelInteraction);

  const handleTabClick = useCallback(
    (tab: RightPanelTab) => {
      recordPanelInteraction();
      setActiveTab(tab);
    },
    [recordPanelInteraction, setActiveTab],
  );

  return (
    <div
      className="flex h-full w-full min-h-0 flex-col"
      onMouseDown={recordPanelInteraction}
    >
      {/* ── Tab bar ─────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-0.5 border-b px-2.5 py-2">
        {tabs.map(({ value, label, icon: Icon }) => {
          const isActive = activeTab === value;
          const badge = tabBadges[value];
          return (
            <button
              key={value}
              onClick={() => handleTabClick(value)}
              className={cn(
                "relative flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-secondary-foreground hover:bg-muted"
              )}
              title={label}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="hidden sm:inline">{label}</span>
              {badge?.type && (
                <span
                  className={cn(
                    "absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full",
                    badge.type === "new" ? "bg-success" : "bg-warning"
                  )}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Context banner (auto-switch) ────────────────────────────── */}
      {activeTab !== "agent" && <ContextBanner tab={activeTab} />}

      {/* ── Tab content — all panels stay mounted ───────────────────── */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <TabPane active={activeTab === "agent"}>
          <PanelErrorBoundary name="Agent">
            <AgentPanel />
          </PanelErrorBoundary>
        </TabPane>
        <TabPane active={activeTab === "map"}>
          <PanelErrorBoundary name="Map">
            <MapPanel />
          </PanelErrorBoundary>
        </TabPane>
        <TabPane active={activeTab === "data"}>
          <PanelErrorBoundary name="Database">
            <DatabasePanel />
          </PanelErrorBoundary>
        </TabPane>
        <TabPane active={activeTab === "charts"}>
          <PanelErrorBoundary name="Charts">
            <ChartGallery />
          </PanelErrorBoundary>
        </TabPane>
      </div>
    </div>
  );
}
