import type { NvlGraphResult } from "@/lib/types";

function asText(value: unknown, fallback: string): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function asWeight(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export function dashboardRowsToNvlGraph(
  rows: Record<string, unknown>[],
  options: { maxNodes?: number; maxRelationships?: number } = {},
): NvlGraphResult {
  const maxNodes = options.maxNodes ?? 60;
  const maxRelationships = options.maxRelationships ?? 120;
  const nodeMap = new Map<string, NvlGraphResult["nodes"][number]>();
  const relationships: NvlGraphResult["relationships"] = [];

  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    const source = asText(row.source ?? row.sourceStage, "");
    const target = asText(row.target ?? row.targetStage, "");
    if (!source || !target) continue;

    const relationship = asText(row.relationship, "RELATED");
    const weight = asWeight(row.weight ?? row.count ?? row.value);
    const sourceType = asText(row.sourceType, source);
    const targetType = asText(row.targetType, target);
    const sourceName = asText(row.sourceName, source);
    const targetName = asText(row.targetName, target);

    if (!nodeMap.has(source)) {
      nodeMap.set(source, {
        id: source,
        labels: [sourceType],
        caption: sourceName,
        properties: {
          stage: source,
          type: sourceType,
        },
      });
    }
    if (!nodeMap.has(target)) {
      nodeMap.set(target, {
        id: target,
        labels: [targetType],
        caption: targetName,
        properties: {
          stage: target,
          type: targetType,
        },
      });
    }

    relationships.push({
      id: `${source}-${relationship}-${target}-${index}`,
      from: source,
      to: target,
      type: relationship,
      caption: `${relationship}: ${weight.toLocaleString()}`,
      properties: {
        relationship,
        weight,
      },
    });
  }

  const nodes = Array.from(nodeMap.values()).slice(0, maxNodes);
  const visibleIds = new Set(nodes.map((node) => node.id));
  const visibleRelationships = relationships
    .filter((relationship) => visibleIds.has(relationship.from) && visibleIds.has(relationship.to))
    .slice(0, maxRelationships);
  const truncated = nodeMap.size > nodes.length || relationships.length > visibleRelationships.length;

  return {
    nodes,
    relationships: visibleRelationships,
    stats: {
      nodeCount: nodes.length,
      relationshipCount: visibleRelationships.length,
      truncated,
    },
    warnings: truncated ? ["Network view is truncated to keep the dashboard responsive."] : [],
  };
}

export function countDashboardRelationships(
  graph: NvlGraphResult,
): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const relationship of graph.relationships) {
    const weight = typeof relationship.properties?.weight === "number" ? relationship.properties.weight : 1;
    counts.set(relationship.type ?? "RELATED", (counts.get(relationship.type ?? "RELATED") ?? 0) + weight);
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}
