"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type NVL from "@neo4j-nvl/base";
import { AlertTriangle, Focus, GitBranch, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, PanelError } from "@/components/shared/EmptyState";
import { useDatabaseStore } from "@/stores/databaseStore";
import type { NvlGraphResult } from "@/lib/types";
import { GraphInspector, type GraphSelection } from "./GraphInspector";
import { NvlGraphCanvas } from "./NvlGraphCanvas";

const SAMPLE_GRAPH_QUERY = "MATCH p=(a)-[r]->(b) RETURN p LIMIT 50";

function hasGraphData(
  graph: NvlGraphResult | null | undefined,
): graph is NvlGraphResult {
  return !!graph && (graph.nodes.length > 0 || graph.relationships.length > 0);
}

export function GraphResultsView({ graph }: { graph?: NvlGraphResult | null }) {
  const nvlRef = useRef<NVL | null>(null);
  const setQuery = useDatabaseStore((s) => s.setQuery);
  const [selection, setSelection] = useState<GraphSelection | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  const warnings = useMemo(() => graph?.warnings ?? [], [graph?.warnings]);

  const handleSampleQuery = useCallback(() => {
    setQuery(SAMPLE_GRAPH_QUERY);
  }, [setQuery]);

  const handleFit = useCallback(() => {
    nvlRef.current?.fit(graph?.nodes.map((node) => node.id) ?? []);
  }, [graph?.nodes]);

  const handleReset = useCallback(() => {
    nvlRef.current?.resetZoom?.();
  }, []);

  const handleRestart = useCallback(() => {
    nvlRef.current?.restart?.();
  }, []);

  if (!hasGraphData(graph)) {
    return (
      <EmptyState
        icon={<GitBranch className="h-8 w-8" />}
        title="No graph entities returned"
        subtitle="Return nodes, relationships, or paths to visualize this query as a graph."
        action={
          <Button size="sm" onClick={handleSampleQuery} className="h-8 text-xs">
            Insert sample graph query
          </Button>
        }
      />
    );
  }

  if (renderError) {
    return (
      <PanelError
        message={`Graph renderer failed: ${renderError}`}
        onRetry={() => setRenderError(null)}
      />
    );
  }

  const graphData = graph;

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_1px_1px,hsl(var(--border))_1px,transparent_0)] [background-size:18px_18px]">
      <div className="absolute left-2 top-2 z-10 flex flex-wrap items-center gap-1 rounded-md border bg-background/90 p-1 shadow-sm backdrop-blur">
        <Button
          size="sm"
          variant="ghost"
          onClick={handleFit}
          className="h-7 gap-1 px-2 text-xs"
          aria-label="Fit graph to view"
        >
          <Focus className="h-3.5 w-3.5" />
          Fit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleReset}
          className="h-7 gap-1 px-2 text-xs"
          aria-label="Reset graph zoom"
        >
          Reset
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleRestart}
          className="h-7 gap-1 px-2 text-xs"
          aria-label="Restart graph layout"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Layout
        </Button>
      </div>

      {warnings.length > 0 && (
        <div className="absolute bottom-2 left-2 z-10 max-w-[calc(100%-1rem)] rounded-md border border-warning/30 bg-background/95 px-2 py-1.5 text-[11px] text-muted-foreground shadow-sm">
          <div className="flex items-start gap-1.5">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <span>{warnings[0]}</span>
          </div>
        </div>
      )}

      <NvlGraphCanvas
        ref={nvlRef}
        graph={graphData}
        onSelect={setSelection}
        onError={(error) =>
          setRenderError(error instanceof Error ? error.message : String(error))
        }
      />

      {selection && (
        <GraphInspector
          selection={selection}
          onClose={() => setSelection(null)}
        />
      )}
    </div>
  );
}
