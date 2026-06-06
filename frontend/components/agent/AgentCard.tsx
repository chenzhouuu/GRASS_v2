"use client";

import { memo } from "react";
import type { AgentPipelineStep } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CheckCircle2, Loader2, Clock, XCircle, ChevronRight } from "lucide-react";

interface AgentCardProps {
  step: AgentPipelineStep;
  expanded: boolean;
  onToggle: () => void;
}

const statusConfig: Record<
  string,
  { icon: React.ElementType; className: string }
> = {
  done: { icon: CheckCircle2, className: "text-emerald-500" },
  running: { icon: Loader2, className: "text-emerald-600 animate-spin" },
  pending: { icon: Clock, className: "text-muted-foreground/60" },
  error: { icon: XCircle, className: "text-destructive" },
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export const AgentCard = memo(function AgentCard({
  step,
  expanded,
  onToggle,
}: AgentCardProps) {
  const config = statusConfig[step.status] ?? statusConfig.pending;
  const Icon = config.icon;
  const hasDetail =
    step.detail.cypherQuery ||
    step.detail.cypherPreview?.length ||
    step.detail.codeOutput ||
    step.detail.error ||
    step.detail.message;

  return (
    <div
      className={cn(
        "rounded-lg border transition-colors",
        step.status === "running" && "border-emerald-500/30 bg-emerald-50/30 dark:bg-emerald-950/10",
        step.status === "done" && "border-border bg-card",
        step.status === "error" && "border-destructive/30 bg-destructive/5",
        step.status === "pending" && "border-border/50 bg-muted/30 opacity-60",
      )}
    >
      {/* Collapsed header — always visible */}
      <button
        onClick={onToggle}
        disabled={!hasDetail}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2.5 text-sm",
          hasDetail && "cursor-pointer hover:bg-accent/50",
          !hasDetail && "cursor-default",
        )}
      >
        <Icon className={cn("h-4 w-4 shrink-0", config.className)} />
        <span className="font-medium flex-1 text-left">{step.agent}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {step.status === "running" && step.startedAt
            ? "..."
            : formatDuration(step.duration)}
        </span>
        {hasDetail && (
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 text-muted-foreground/60 transition-transform",
              expanded && "rotate-90",
            )}
          />
        )}
      </button>

      {/* Expanded detail */}
      {expanded && hasDetail && (
        <div className="border-t px-3 py-2.5 text-xs space-y-2">
          {step.detail.error && (
            <p className="text-destructive">{step.detail.error}</p>
          )}

          {step.detail.cypherQuery && (
            <div>
              <p className="font-medium text-muted-foreground mb-1">Cypher Query</p>
              <pre className="rounded bg-muted p-2 overflow-x-auto text-[11px] leading-relaxed whitespace-pre-wrap">
                {step.detail.cypherQuery}
              </pre>
            </div>
          )}

          {step.detail.cypherPreview && step.detail.cypherPreview.length > 0 && (
            <div>
              <p className="font-medium text-muted-foreground mb-1">
                Preview ({step.detail.cypherPreview.length} rows)
              </p>
              <div className="overflow-x-auto rounded border">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-muted/50">
                      {Object.keys(step.detail.cypherPreview[0]).map((col) => (
                        <th key={col} className="px-2 py-1 text-left font-medium">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {step.detail.cypherPreview.map((row, i) => (
                      <tr key={i} className="border-t">
                        {Object.values(row).map((val, j) => (
                          <td key={j} className="px-2 py-1 truncate max-w-[120px]">
                            {String(val ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {step.detail.codeOutput && (
            <div>
              <p className="font-medium text-muted-foreground mb-1">Output</p>
              <pre className="rounded bg-muted p-2 overflow-x-auto text-[11px] leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
                {step.detail.codeOutput}
              </pre>
            </div>
          )}

          {step.detail.message && !step.detail.error && (
            <p className="text-muted-foreground">{step.detail.message}</p>
          )}
        </div>
      )}
    </div>
  );
});
