"use client";

import { useEffect } from "react";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition } from "@/lib/types";

function getBarLabel(row: Record<string, unknown>): string {
  return String(row.label ?? row.type ?? row.name ?? "Unknown");
}

function getBarCount(row: Record<string, unknown>): number {
  const value = row.count ?? row.value;
  return typeof value === "number" ? value : Number(value ?? 0);
}

export function BarCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const rows = result?.rows ?? [];
  const max = Math.max(1, ...rows.map((row) => getBarCount(row)));

  return (
    <DashboardCardShell card={card} result={result} loading={executing && !result}>
      <div className="space-y-2">
        {rows.slice(0, 8).map((row, index) => {
          const count = getBarCount(row);
          const label = getBarLabel(row);
          return (
            <div key={`${label}-${index}`} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="truncate font-medium">{label}</span>
                <span className="text-muted-foreground">{count.toLocaleString()}</span>
              </div>
              <div className="h-2 rounded-full bg-muted">
                <div
                  className="h-2 rounded-full bg-primary"
                  style={{ width: `${Math.max(4, (count / max) * 100)}%` }}
                />
              </div>
            </div>
          );
        })}
        {rows.length === 0 && result?.status === "success" ? (
          <p className="text-sm text-muted-foreground">No rows returned.</p>
        ) : null}
      </div>
    </DashboardCardShell>
  );
}
