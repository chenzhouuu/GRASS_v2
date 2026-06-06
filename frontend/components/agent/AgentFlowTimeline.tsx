"use client";

import { memo } from "react";
import type { AgentPipelineStep } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CheckCircle2, Loader2, Clock, XCircle, ChevronRight } from "lucide-react";

interface AgentFlowTimelineProps {
  steps: AgentPipelineStep[];
  expandedSteps: Record<string, boolean>;
  onToggle: (stepId: string) => void;
}

const statusConfig: Record<
  string,
  { icon: React.ElementType; badgeClass: string; borderClass: string; badgeText: string }
> = {
  done: {
    icon: CheckCircle2,
    badgeClass: "bg-success/10 text-success",
    borderClass: "border-success/30",
    badgeText: "DONE",
  },
  running: {
    icon: Loader2,
    badgeClass: "bg-info/10 text-info",
    borderClass: "border-info/30",
    badgeText: "RUNNING",
  },
  pending: {
    icon: Clock,
    badgeClass: "bg-muted text-muted-foreground",
    borderClass: "border-border/50",
    badgeText: "PENDING",
  },
  error: {
    icon: XCircle,
    badgeClass: "bg-destructive/10 text-destructive",
    borderClass: "border-destructive/30",
    badgeText: "ERROR",
  },
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function isWorkerAgent(agent: string): boolean {
  return agent !== "Supervisor";
}

const TimelineStep = memo(function TimelineStep({
  step,
  expanded,
  onToggle,
  isLast,
  prevAgent,
}: {
  step: AgentPipelineStep;
  expanded: boolean;
  onToggle: () => void;
  isLast: boolean;
  prevAgent: string | null;
}) {
  const config = statusConfig[step.status] ?? statusConfig.pending;
  const Icon = config.icon;
  const isWorker = isWorkerAgent(step.agent);
  const hasDetail =
    step.detail.cypherQuery ||
    step.detail.cypherPreview?.length ||
    step.detail.codeOutput ||
    step.detail.error ||
    step.detail.message;

  const showDispatch = isWorker && prevAgent === "Supervisor";
  const showReturn = step.agent === "Supervisor" && prevAgent && isWorkerAgent(prevAgent);

  return (
    <div className="relative">
      {showDispatch && (
        <div className="flex items-center gap-1.5 pl-4 py-1">
          <span className="text-muted-foreground text-2xs">╰→</span>
          <span className="text-2xs text-primary">dispatched {step.agent.toLowerCase()}</span>
        </div>
      )}

      {showReturn && (
        <div className="flex items-center gap-1.5 pl-8 py-1">
          <span className="text-muted-foreground text-2xs">╰┄</span>
          <span className="text-2xs text-muted-foreground">returned to Supervisor</span>
        </div>
      )}

      <div
        className={cn(
          "relative rounded-lg border transition-colors",
          config.borderClass,
          isWorker && "ml-4",
          step.status === "running" && "border-l-[3px] border-l-info",
          step.status === "done" && "bg-card",
          step.status === "error" && "bg-destructive/5",
          step.status === "pending" && "opacity-60",
        )}
      >
        <button
          onClick={onToggle}
          disabled={!hasDetail}
          className={cn(
            "flex w-full items-center gap-2 px-3 py-2.5 text-sm",
            hasDetail && "cursor-pointer hover:bg-accent/30",
            !hasDetail && "cursor-default",
          )}
        >
          <Icon
            className={cn(
              "h-4 w-4 shrink-0",
              step.status === "done" && "text-success",
              step.status === "running" && "text-info animate-spin",
              step.status === "pending" && "text-muted-foreground/60",
              step.status === "error" && "text-destructive",
            )}
          />
          <span className="font-semibold text-sm flex-1 text-left">{step.agent}</span>

          <span className={cn("rounded px-1.5 py-0.5 text-[9px] uppercase font-medium", config.badgeClass)}>
            {step.status === "running" ? (
              <span className="status-pulse">{config.badgeText}</span>
            ) : (
              config.badgeText
            )}
          </span>

          <span className="text-2xs text-muted-foreground tabular-nums min-w-[40px] text-right">
            {step.status === "running" && step.startedAt ? "..." : formatDuration(step.duration)}
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

        {expanded && hasDetail && (
          <div className="border-t px-3 py-2.5 text-sm space-y-2">
            {step.detail.error && (
              <p className="text-destructive">{step.detail.error}</p>
            )}

            {step.detail.cypherQuery && (
              <div>
                <p className="font-medium text-muted-foreground mb-1 text-xs">Cypher Query</p>
                <pre className="rounded bg-muted p-2 overflow-x-auto text-xs leading-relaxed whitespace-pre-wrap font-[var(--font-geist-mono)]">
                  {step.detail.cypherQuery}
                </pre>
              </div>
            )}

            {step.detail.cypherPreview && step.detail.cypherPreview.length > 0 && (
              <div>
                <p className="font-medium text-muted-foreground mb-1 text-xs">
                  Preview ({step.detail.cypherPreview.length} rows)
                </p>
                <div className="overflow-x-auto rounded border">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-muted/50">
                        {Object.keys(step.detail.cypherPreview[0]).map((col) => (
                          <th key={col} className="px-2 py-1 text-left font-medium text-2xs uppercase">
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
                <p className="font-medium text-muted-foreground mb-1 text-xs">Output</p>
                <pre className="rounded bg-muted p-2 overflow-x-auto text-xs leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto font-[var(--font-geist-mono)]">
                  {step.detail.codeOutput}
                </pre>
              </div>
            )}

            {step.detail.message && !step.detail.error && (
              <p className="text-muted-foreground text-xs">{step.detail.message}</p>
            )}
          </div>
        )}
      </div>

      {!isLast && (
        <div className="absolute left-[18px] top-full h-2 w-0.5 bg-border" />
      )}
    </div>
  );
});

export const AgentFlowTimeline = memo(function AgentFlowTimeline({
  steps,
  expandedSteps,
  onToggle,
}: AgentFlowTimelineProps) {
  return (
    <div className="relative space-y-1.5">
      <div className="absolute left-[18px] top-0 bottom-0 w-0.5 bg-muted" />

      {steps.map((step, index) => (
        <TimelineStep
          key={step.id}
          step={step}
          expanded={!!expandedSteps[step.id]}
          onToggle={() => onToggle(step.id)}
          isLast={index === steps.length - 1}
          prevAgent={index > 0 ? steps[index - 1].agent : null}
        />
      ))}
    </div>
  );
});
