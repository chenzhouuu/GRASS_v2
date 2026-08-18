"use client";

import { forwardRef, useMemo } from "react";
import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import type NVL from "@neo4j-nvl/base";
import type { ExternalCallbacks, Node, Relationship } from "@neo4j-nvl/base";
import type { MouseEventCallbacks } from "@neo4j-nvl/react";
import type { GraphSelection } from "./GraphInspector";
import type { NvlGraphResult } from "@/lib/types";

const LABEL_COLORS = [
  "#10b981",
  "#38bdf8",
  "#f59e0b",
  "#a78bfa",
  "#f472b6",
  "#84cc16",
  "#fb7185",
  "#22d3ee",
];

function hashString(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function colorForLabel(label: string) {
  return LABEL_COLORS[hashString(label) % LABEL_COLORS.length];
}

export const NvlGraphCanvas = forwardRef<
  NVL,
  {
    graph: NvlGraphResult;
    onSelect: (selection: GraphSelection | null) => void;
    onError: (error: unknown) => void;
    nodeSize?: number;
    captionSize?: number;
    relationshipCaptionSize?: number;
    initialZoom?: number;
    nvlCallbacks?: ExternalCallbacks;
  }
>(function NvlGraphCanvas(
  {
    graph,
    onSelect,
    onError,
    nodeSize = 32,
    captionSize = 11,
    relationshipCaptionSize = 9,
    initialZoom = 0.7,
    nvlCallbacks,
  },
  ref,
) {
  const nodeById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const relById = useMemo(
    () => new Map(graph.relationships.map((rel) => [rel.id, rel])),
    [graph.relationships],
  );

  const nodes = useMemo<Node[]>(
    () =>
      graph.nodes.map((node) => {
        const primaryLabel = node.labels?.[0] ?? "Node";
        return {
          id: node.id,
          caption: node.caption ?? primaryLabel,
          color: colorForLabel(primaryLabel),
          size: nodeSize,
          captionSize,
          captionAlign: "center" as const,
        };
      }),
    [graph.nodes, nodeSize, captionSize],
  );

  const rels = useMemo<Relationship[]>(
    () =>
      graph.relationships.map((rel) => ({
        id: rel.id,
        from: rel.from,
        to: rel.to,
        type: rel.type,
        caption: rel.caption ?? rel.type,
        color: "#94a3b8",
        width: 1.5,
        captionSize: relationshipCaptionSize,
      })),
    [graph.relationships, relationshipCaptionSize],
  );

  const mouseEventCallbacks = useMemo<MouseEventCallbacks>(
    () => ({
      onNodeClick: (node) => {
        const entity = nodeById.get(node.id);
        if (entity) onSelect({ kind: "node", entity });
      },
      onRelationshipClick: (relationship) => {
        const entity = relById.get(relationship.id);
        if (entity) onSelect({ kind: "relationship", entity });
      },
      onCanvasClick: () => onSelect(null),
    }),
    [nodeById, onSelect, relById],
  );

  return (
    <InteractiveNvlWrapper
      ref={ref}
      className="h-full w-full"
      nodes={nodes}
      rels={rels}
      layout="forceDirected"
      nvlCallbacks={nvlCallbacks}
      nvlOptions={{
        renderer: "canvas",
        initialZoom,
        disableTelemetry: true,
      }}
      interactionOptions={{
        selectOnClick: true,
        drawShadowOnHover: true,
      }}
      mouseEventCallbacks={mouseEventCallbacks}
      onInitializationError={onError}
    />
  );
});
