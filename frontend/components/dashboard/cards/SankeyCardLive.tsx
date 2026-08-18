"use client";

import { useEffect, useMemo } from "react";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { InteractiveChart } from "@/components/visualization/InteractiveChart";
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition, VisualizationData } from "@/lib/types";

function asText(value: unknown, fallback: string): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function asValue(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export function SankeyCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const visualization = useMemo<VisualizationData | null>(() => {
    const rows = result?.rows ?? [];
    if (!rows.length) return null;

    const labels: string[] = [];
    const labelIndex = new Map<string, number>();
    const source: number[] = [];
    const target: number[] = [];
    const value: number[] = [];
    const linkLabels: string[] = [];

    function indexFor(label: string): number {
      const existing = labelIndex.get(label);
      if (existing !== undefined) return existing;
      const next = labels.length;
      labels.push(label);
      labelIndex.set(label, next);
      return next;
    }

    for (const row of rows) {
      const sourceStage = asText(row.sourceStage ?? row.source, "Source");
      const targetStage = asText(row.targetStage ?? row.target, "Target");
      source.push(indexFor(sourceStage));
      target.push(indexFor(targetStage));
      value.push(asValue(row.count ?? row.value ?? row.weight));
      linkLabels.push(asText(row.relationship, `${sourceStage} to ${targetStage}`));
    }

    return {
      id: card.id,
      type: "chart",
      title: card.title,
      data: {
        data: [
          {
            type: "sankey",
            arrangement: "snap",
            node: {
              label: labels,
              pad: 14,
              thickness: 14,
              color: labels.map((_, index) => {
                const palette = ["#0f766e", "#2563eb", "#9333ea", "#ea580c", "#dc2626", "#0891b2"];
                return palette[index % palette.length];
              }),
            },
            link: {
              source,
              target,
              value,
              label: linkLabels,
              color: "rgba(15, 118, 110, 0.22)",
            },
          },
        ],
        layout: {
          height: 320,
          showlegend: false,
        },
      },
    };
  }, [card.id, card.title, result?.rows]);

  return (
    <DashboardCardShell card={card} result={result} loading={executing && !result}>
      {visualization ? (
        <div className="h-[340px]">
          <InteractiveChart visualization={visualization} compact showDownloadButton={false} />
        </div>
      ) : result?.status === "success" ? (
        <p className="text-sm text-muted-foreground">No flow rows returned.</p>
      ) : null}
    </DashboardCardShell>
  );
}
