"use client";

import { useEffect, useMemo } from "react";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition } from "@/lib/types";

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function TableCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const rows = result?.rows ?? [];
  const columns = useMemo(
    () => Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 8),
    [rows],
  );

  return (
    <DashboardCardShell card={card} result={result} loading={executing && !result}>
      {rows.length === 0 && result?.status === "success" ? (
        <p className="text-sm text-muted-foreground">No rows returned.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <div className="max-h-[320px] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-muted text-muted-foreground">
                <tr>
                  {columns.map((column) => (
                    <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 20).map((row, rowIndex) => (
                  <tr key={rowIndex} className="border-t">
                    {columns.map((column) => (
                      <td key={column} className="max-w-[220px] truncate px-3 py-2">
                        {formatCell(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {result?.sampled ? (
        <p className="mt-2 text-xs text-muted-foreground">{result.sampleNote}</p>
      ) : null}
    </DashboardCardShell>
  );
}
