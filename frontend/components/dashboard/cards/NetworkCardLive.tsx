"use client";

import { useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { GitBranch } from "lucide-react";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { countDashboardRelationships, dashboardRowsToNvlGraph } from "@/lib/dashboardNetwork";

// @neo4j-nvl touches `document` at import time, which breaks static
// prerendering of /dashboards — load the graph canvas client-side only.
const DashboardNetworkGraph = dynamic(
  () =>
    import("@/components/dashboard/cards/DashboardNetworkGraph").then(
      (m) => m.DashboardNetworkGraph,
    ),
  { ssr: false },
);
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition } from "@/lib/types";

export function NetworkCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const graph = useMemo(
    () => dashboardRowsToNvlGraph(result?.rows ?? []),
    [result?.rows],
  );
  const relationshipCounts = useMemo(() => countDashboardRelationships(graph).slice(0, 6), [graph]);

  return (
    <DashboardCardShell card={card} result={result} loading={executing && !result}>
      {graph.nodes.length === 0 && result?.status === "success" ? (
        <p className="text-sm text-muted-foreground">No relationship rows returned.</p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px]">
          <DashboardNetworkGraph graph={graph} />
          <div className="space-y-2">
            <p className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <GitBranch className="h-3 w-3" />
              Top flow types
            </p>
            {relationshipCounts.map(([relationship, count]) => (
              <div key={relationship} className="rounded-md border px-2 py-1.5 text-xs">
                <div className="truncate font-medium">{relationship}</div>
                <div className="text-muted-foreground">{count.toLocaleString()} relationships</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {result?.sampled ? (
        <p className="mt-2 text-xs text-muted-foreground">{result.sampleNote}</p>
      ) : null}
    </DashboardCardShell>
  );
}
