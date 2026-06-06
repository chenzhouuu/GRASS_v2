"use client";

import { ArrowRight, X } from "lucide-react";
import { useAppStore, type RightPanelTab } from "@/stores/appStore";

const TAB_LABELS: Record<RightPanelTab, string> = {
  agent: "Agent pipeline",
  map: "Map view",
  data: "Query results",
  charts: "Charts",
};

interface ContextBannerProps {
  tab: RightPanelTab;
}

export function ContextBanner({ tab }: ContextBannerProps) {
  const autoSwitchEnabled = useAppStore((s) => s.autoSwitchEnabled);
  const setAutoSwitchEnabled = useAppStore((s) => s.setAutoSwitchEnabled);

  if (!autoSwitchEnabled) return null;

  return (
    <div className="flex items-center gap-2 border-b bg-accent-subtle px-3 py-1.5">
      <ArrowRight className="h-3 w-3 text-primary" />
      <span className="flex-1 text-2xs text-primary">
        Switched to {TAB_LABELS[tab]} — new data available
      </span>
      <button
        onClick={() => setAutoSwitchEnabled(false)}
        className="flex items-center gap-1 text-2xs text-muted-foreground hover:text-foreground transition-colors"
      >
        Auto
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
