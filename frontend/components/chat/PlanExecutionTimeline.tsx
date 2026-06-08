"use client";

import { cn } from "@/lib/utils";
import type { LedgerPhase, LedgerProgress, LedgerStepStatus } from "@/lib/types";
import { Check, Loader2, AlertCircle } from "lucide-react";

const PHASE_LABEL: Record<LedgerPhase, string> = {
  executing: "Executing plan",
  replanning: "Revising plan",
  finalizing: "Finalizing",
  complete: "Plan complete",
};

const AGENT_TINT: Record<string, string> = {
  Cypher: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  Analytics: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  Optimization: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  Report: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  ScenarioRunner: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
};

interface PlanExecutionTimelineProps {
  progress: LedgerProgress;
}

/**
 * Live execution timeline for the progress-ledger Executor. Renders the
 * approved plan as a vertical rail whose nodes animate pending → running →
 * done as the ledger advances (streamed via the `progress` SSE event).
 */
export function PlanExecutionTimeline({ progress }: PlanExecutionTimelineProps) {
  const { phase, current_step, total_steps, summary, steps } = progress;
  const done = steps.filter((s) => s.status === "done").length;
  const pct = total_steps > 0 ? Math.round((done / total_steps) * 100) : 0;
  const complete = phase === "complete";

  return (
    <div className="mt-3 flex justify-start">
      <div
        className={cn(
          "w-full max-w-2xl overflow-hidden rounded-xl border shadow-sm",
          "bg-gradient-to-br from-slate-50 to-slate-100/70",
          "dark:from-slate-900 dark:to-slate-800/70 dark:border-slate-700",
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-2.5 px-4 pt-3 pb-2.5">
          {complete ? (
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-white">
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
          ) : (
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500/60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
            </span>
          )}
          <span className="text-sm font-semibold text-foreground">{PHASE_LABEL[phase]}</span>
          <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
            {Math.min(current_step, total_steps)}/{total_steps}
          </span>
        </div>

        {/* Progress bar */}
        <div className="mx-4 mb-3 h-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-700/60">
          <div
            className="h-full rounded-full bg-emerald-500 transition-[width] duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Step rail */}
        <ol className="px-4 pb-3.5">
          {steps.map((step, i) => {
            const isLast = i === steps.length - 1;
            const connectorDone = step.status === "done";
            return (
              <li key={step.index} className="relative flex gap-3 pb-2.5 last:pb-0">
                {!isLast && (
                  <span
                    className={cn(
                      "absolute left-[10px] top-[22px] w-px",
                      "h-[calc(100%-1rem)]",
                      connectorDone
                        ? "bg-emerald-400/70 dark:bg-emerald-500/50"
                        : "bg-slate-200 dark:bg-slate-700",
                    )}
                    aria-hidden
                  />
                )}
                <StepNode status={step.status} index={step.index} />
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "truncate text-sm",
                        step.status === "running" && "font-medium text-foreground",
                        step.status === "done" && "text-foreground/75",
                        step.status === "pending" && "text-muted-foreground",
                        step.status === "error" && "font-medium text-red-600 dark:text-red-400",
                      )}
                    >
                      {step.title}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-px text-[10px] font-medium",
                        AGENT_TINT[step.agent] ??
                          "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300",
                      )}
                    >
                      {step.agent}
                    </span>
                  </div>
                  {step.status === "running" && summary && (
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">{summary}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function StepNode({ status, index }: { status: LedgerStepStatus; index: number }) {
  const base = "relative z-10 flex h-[21px] w-[21px] shrink-0 items-center justify-center rounded-full";
  if (status === "done") {
    return (
      <span className={cn(base, "bg-emerald-500 text-white")}>
        <Check className="h-3 w-3" strokeWidth={3} />
      </span>
    );
  }
  if (status === "running") {
    return (
      <span
        className={cn(
          base,
          "border-2 border-emerald-500 bg-background text-emerald-600",
          "ring-4 ring-emerald-500/15 dark:text-emerald-400",
        )}
      >
        <Loader2 className="h-3 w-3 animate-spin" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className={cn(base, "bg-red-500 text-white")}>
        <AlertCircle className="h-3 w-3" />
      </span>
    );
  }
  return (
    <span
      className={cn(
        base,
        "border border-slate-300 bg-background text-[10px] font-semibold text-muted-foreground",
        "dark:border-slate-600",
      )}
    >
      {index}
    </span>
  );
}
