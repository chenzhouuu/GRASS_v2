"use client";

import { useCallback } from "react";
import dynamic from "next/dynamic";
import { Maximize2, Loader2 } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import type { VisualizationData } from "@/lib/types";

const InteractiveChart = dynamic(
  () =>
    import("@/components/visualization/InteractiveChart").then(
      (m) => m.InteractiveChart
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    ),
  }
);

function hasTallChart(viz: VisualizationData): boolean {
  const spec = viz.data as Record<string, unknown> | undefined;
  if (!spec) return false;
  const layout = spec.layout as Record<string, unknown> | undefined;
  if (layout?.height && typeof layout.height === "number" && layout.height > 500) return true;
  const data = spec.data as Array<Record<string, unknown>> | undefined;
  if (data?.some((t) => t.type === "sankey")) return true;
  return false;
}

interface InlineChartProps {
  visualization: VisualizationData;
}

export function InlineChart({ visualization }: InlineChartProps) {
  const setActiveTab = useAppStore((s) => s.setActiveRightTab);

  const handleExpand = useCallback(() => {
    setActiveTab("charts");
  }, [setActiveTab]);

  return (
    <div className="overflow-hidden rounded-lg border bg-background">
      {visualization.title && (
        <div className="flex items-center justify-between border-b px-3.5 py-2">
          <span className="text-xs font-medium truncate">
            {visualization.title}
          </span>
          <button
            onClick={handleExpand}
            className="flex items-center gap-1 text-2xs text-muted-foreground hover:text-primary transition-colors shrink-0"
            title="Open in Charts tab"
          >
            <Maximize2 className="h-3 w-3" />
            Expand
          </button>
        </div>
      )}
      <div className="min-h-[250px] overflow-auto" style={{
        maxHeight: hasTallChart(visualization) ? "80vh" : "500px",
        height: hasTallChart(visualization) ? "auto" : "40vh",
      }}>
        <InteractiveChart visualization={visualization} compact={!hasTallChart(visualization)} />
      </div>
      {!visualization.title && (
        <div className="flex justify-end border-t px-2 py-1">
          <button
            onClick={handleExpand}
            className="flex items-center gap-1 text-2xs text-muted-foreground hover:text-primary transition-colors px-1.5"
            title="Open in Charts tab"
          >
            <Maximize2 className="h-3 w-3" />
            Expand
          </button>
        </div>
      )}
    </div>
  );
}
