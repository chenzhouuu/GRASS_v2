"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { DashboardCardDefinition, DashboardCardResult } from "@/lib/types";

interface DashboardCardShellProps {
  card: DashboardCardDefinition;
  result?: DashboardCardResult;
  loading?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}

export function DashboardCardShell({
  card,
  result,
  loading = false,
  actions,
  children,
}: DashboardCardShellProps) {
  return (
    <article className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">{card.title}</h3>
            {!card.exact && (
              <Badge variant="outline" className="text-2xs">
                Estimated
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{card.description}</p>
        </div>
        {actions}
      </div>
      <div className="mt-4 min-h-[72px]">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading live data...
          </div>
        ) : result?.status === "error" ? (
          <div className="flex items-start gap-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{result.error || "Failed to load card"}</span>
          </div>
        ) : (
          children
        )}
      </div>
    </article>
  );
}
