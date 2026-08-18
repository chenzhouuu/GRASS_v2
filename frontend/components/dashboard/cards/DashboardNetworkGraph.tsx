"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type NVL from "@neo4j-nvl/base";
import type { ExternalCallbacks } from "@neo4j-nvl/base";
import { AlertTriangle, Focus, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { NvlGraphCanvas } from "@/components/database/NvlGraphCanvas";
import type { GraphSelection } from "@/components/database/GraphInspector";
import type { NvlGraphResult } from "@/lib/types";

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function SelectionPanel({
  selection,
  onClose,
}: {
  selection: GraphSelection;
  onClose: () => void;
}) {
  const entity = selection.entity;
  const title = entity.caption || entity.id;
  const badges =
    selection.kind === "node"
      ? selection.entity.labels ?? []
      : [selection.entity.type || "Relationship"];
  const properties = entity.properties ?? {};

  return (
    <aside className="absolute right-2 top-2 z-20 flex max-h-[calc(100%-1rem)] w-64 flex-col overflow-hidden rounded-lg border bg-background/95 shadow-lg backdrop-blur">
      <div className="flex items-start gap-2 border-b px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{title}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {badges.map((badge) => (
              <Badge key={badge} variant="secondary" className="px-1.5 py-0 text-[10px]">
                {badge}
              </Badge>
            ))}
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onClose}
          className="h-7 w-7 shrink-0 p-0"
          aria-label="Close network details"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-3 py-2">
        {Object.keys(properties).length === 0 ? (
          <p className="text-xs text-muted-foreground">No aggregate properties on this item.</p>
        ) : (
          <div className="divide-y rounded border">
            {Object.entries(properties).map(([key, value]) => (
              <div key={key} className="grid grid-cols-[5rem_1fr] gap-2 px-2 py-1.5 text-xs">
                <span className="truncate font-mono text-muted-foreground">{key}</span>
                <span className="min-w-0 break-words">{formatValue(value)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

export function DashboardNetworkGraph({ graph }: { graph: NvlGraphResult }) {
  const nvlRef = useRef<NVL | null>(null);
  const hasAutoFittedRef = useRef(false);
  const [selection, setSelection] = useState<GraphSelection | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  const nodeIds = useMemo(() => graph.nodes.map((node) => node.id), [graph.nodes]);

  const handleFit = useCallback(() => {
    nvlRef.current?.fit?.(nodeIds);
  }, [nodeIds]);

  const handleReset = useCallback(() => {
    // For the compact dashboard card, "reset" means fit the whole network back into view.
    nvlRef.current?.fit?.(nodeIds);
  }, [nodeIds]);

  const handleRestart = useCallback(() => {
    setSelection(null);
    hasAutoFittedRef.current = false;
    nvlRef.current?.restart?.();
  }, []);

  // Auto-fit the network into the panel the first time the force layout settles
  // so every stage node (and its on-node label) is visible without manual
  // zooming. Only fit once so we do not fight the user after they pan/drag.
  const nvlCallbacks = useMemo<ExternalCallbacks>(
    () => ({
      onLayoutDone: () => {
        if (hasAutoFittedRef.current) return;
        hasAutoFittedRef.current = true;
        nvlRef.current?.fit?.(nodeIds);
      },
    }),
    [nodeIds],
  );

  if (renderError) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <AlertTriangle className="mr-2 h-4 w-4" />
        Network renderer failed: {renderError}
      </div>
    );
  }

  return (
    <div className="relative h-[360px] overflow-hidden rounded-lg border bg-[radial-gradient(circle_at_1px_1px,hsl(var(--border))_1px,transparent_0)] [background-size:18px_18px]">
      <div className="absolute left-2 top-2 z-10 flex flex-wrap items-center gap-1 rounded-md border bg-background/90 p-1 shadow-sm backdrop-blur">
        <Button
          size="sm"
          variant="ghost"
          onClick={handleFit}
          className="h-7 gap-1 px-2 text-xs"
          aria-label="Refit dashboard network"
        >
          <Focus className="h-3.5 w-3.5" />
          Fit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleReset}
          className="h-7 px-2 text-xs"
          aria-label="Reset dashboard network zoom"
        >
          Reset
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleRestart}
          className="h-7 gap-1 px-2 text-xs"
          aria-label="Restart dashboard network layout"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Layout
        </Button>
      </div>

      <div className="absolute bottom-2 left-2 z-10 rounded-md border bg-background/90 px-2 py-1 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
        {graph.stats?.nodeCount ?? graph.nodes.length} stages ·{" "}
        {graph.stats?.relationshipCount ?? graph.relationships.length} flows
      </div>

      {graph.warnings?.[0] ? (
        <div className="absolute bottom-2 right-2 z-10 max-w-[16rem] rounded-md border border-amber-500/30 bg-background/95 px-2 py-1.5 text-[11px] text-muted-foreground shadow-sm">
          <div className="flex items-start gap-1.5">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span>{graph.warnings[0]}</span>
          </div>
        </div>
      ) : null}

      <NvlGraphCanvas
        ref={nvlRef}
        graph={graph}
        nodeSize={40}
        captionSize={3}
        relationshipCaptionSize={2}
        initialZoom={0.4}
        nvlCallbacks={nvlCallbacks}
        onSelect={setSelection}
        onError={(error) => setRenderError(error instanceof Error ? error.message : String(error))}
      />

      {selection ? (
        <SelectionPanel selection={selection} onClose={() => setSelection(null)} />
      ) : null}
    </div>
  );
}
