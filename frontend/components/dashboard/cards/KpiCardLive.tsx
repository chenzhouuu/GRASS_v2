"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { buildDrilldownUrl } from "@/lib/dashboardDrilldown";
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition } from "@/lib/types";

function formatValue(value: number | null | undefined, card: DashboardCardDefinition): string {
  if (value == null) return "—";
  if (card.valueFormat === "percent" || card.unit === "percent") {
    return `${Math.round(value * 100)}%`;
  }
  if (card.valueFormat === "decimal") {
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
    }).format(value);
  }
  if (card.valueFormat === "compact") {
    return new Intl.NumberFormat(undefined, {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return new Intl.NumberFormat().format(Math.round(value));
}

export function KpiCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const drilldown = card.drilldown?.template;

  return (
    <DashboardCardShell
      card={card}
      result={result}
      loading={executing && !result}
      actions={
        drilldown ? (
          <Button asChild variant="ghost" size="sm">
            <Link href={buildDrilldownUrl(drilldown)} aria-label={`Explore ${card.title}`}>
              <ExternalLink className="h-4 w-4" />
            </Link>
          </Button>
        ) : undefined
      }
    >
      <p className="text-3xl font-semibold tracking-tight">{formatValue(result?.value, card)}</p>
      {card.unit && card.unit !== "count" && card.unit !== "percent" ? (
        <p className="mt-1 text-xs text-muted-foreground">{card.unit}</p>
      ) : null}
      {result?.executionMs ? (
        <p className="mt-2 text-2xs text-muted-foreground">{result.executionMs}ms</p>
      ) : null}
    </DashboardCardShell>
  );
}
