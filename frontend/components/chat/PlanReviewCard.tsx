"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { submitPlanDecision } from "@/lib/sse";
import type { AgentName, CoPlanStep, PlanReviewPayload } from "@/lib/types";
import {
  ClipboardList,
  Check,
  RefreshCw,
  Trash2,
  ArrowUp,
  ArrowDown,
  Plus,
  Eye,
  EyeOff,
} from "lucide-react";

const WORKER_AGENTS: AgentName[] = ["Cypher", "Analytics", "Optimization", "Report", "ScenarioRunner"];

interface PlanReviewCardProps {
  payload: PlanReviewPayload;
  assistantMessageId: string;
}

/**
 * Co-planning review card: lets the user accept, edit, or request changes to a
 * proposed plan, then resumes the run via submitPlanDecision (Magentic-UI
 * co-planning UX ported to the GRASS plan/plan-decision contract).
 */
export function PlanReviewCard({ payload, assistantMessageId }: PlanReviewCardProps) {
  const [steps, setSteps] = useState<CoPlanStep[]>(() =>
    payload.plan.steps.map((s) => ({ enabled: true, ...s })),
  );
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const patchStep = useCallback((i: number, patch: Partial<CoPlanStep>) => {
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }, []);

  const moveStep = useCallback((i: number, dir: -1 | 1) => {
    setSteps((prev) => {
      const target = i + dir;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[target]] = [next[target], next[i]];
      return next;
    });
  }, []);

  const removeStep = useCallback((i: number) => {
    setSteps((prev) => prev.filter((_, idx) => idx !== i));
  }, []);

  const addStep = useCallback(() => {
    setSteps((prev) => [
      ...prev,
      { title: "New step", details: "", agent: "Cypher", enabled: true },
    ]);
  }, []);

  const submit = useCallback(
    (decision: "accept" | "revise") => {
      setSubmitting(true);
      submitPlanDecision({
        runId: payload.run_id,
        assistantMessageId,
        decision,
        steps,
        content: feedback || undefined,
      });
      // pendingReview is cleared by the resume; this card unmounts.
    },
    [payload.run_id, assistantMessageId, steps, feedback],
  );

  const enabledCount = steps.filter((s) => s.enabled !== false).length;

  return (
    <div className="mt-3 flex justify-start">
      <div
        className={cn(
          "w-full max-w-2xl rounded-xl border shadow-sm",
          "bg-gradient-to-br from-slate-50 to-slate-100/80",
          "dark:from-slate-900 dark:to-slate-800/80 dark:border-slate-700",
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-2 border-b px-4 py-3 dark:border-slate-700">
          <ClipboardList className="h-4 w-4 text-emerald-600" />
          <span className="text-sm font-semibold">Review plan</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {enabledCount} step{enabledCount === 1 ? "" : "s"}
          </span>
        </div>

        {/* Summary */}
        {(payload.summary || payload.plan.summary) && (
          <p className="px-4 pt-3 text-xs text-muted-foreground">
            {payload.summary || payload.plan.summary}
          </p>
        )}

        {/* Editable steps */}
        <div className="space-y-2 px-4 py-3">
          {steps.map((step, i) => {
            const disabled = step.enabled === false;
            return (
              <div
                key={i}
                className={cn(
                  "rounded-md border bg-white/70 p-2.5 dark:bg-slate-800/60 dark:border-slate-600",
                  disabled && "opacity-50",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                    {i + 1}
                  </span>
                  <Input
                    value={step.title}
                    onChange={(e) => patchStep(i, { title: e.target.value })}
                    className="h-7 flex-1 text-sm"
                    placeholder="Step title"
                  />
                  <select
                    value={step.agent}
                    onChange={(e) => patchStep(i, { agent: e.target.value as AgentName })}
                    className="h-7 rounded-md border bg-background px-1.5 text-xs dark:border-slate-600"
                  >
                    {WORKER_AGENTS.map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => patchStep(i, { enabled: disabled })}
                      title={disabled ? "Enable step" : "Disable step"}
                      className="rounded p-1 hover:bg-slate-200 dark:hover:bg-slate-700"
                    >
                      {disabled ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => moveStep(i, -1)}
                      disabled={i === 0}
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-30 dark:hover:bg-slate-700"
                    >
                      <ArrowUp className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => moveStep(i, 1)}
                      disabled={i === steps.length - 1}
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-30 dark:hover:bg-slate-700"
                    >
                      <ArrowDown className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeStep(i)}
                      disabled={steps.length <= 1}
                      className="rounded p-1 text-destructive hover:bg-red-100 disabled:opacity-30 dark:hover:bg-red-900/30"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
                <textarea
                  value={step.details}
                  onChange={(e) => patchStep(i, { details: e.target.value })}
                  rows={2}
                  placeholder="Details"
                  className="mt-1.5 w-full resize-y rounded-md border bg-background px-2 py-1 text-xs dark:border-slate-600"
                />
              </div>
            );
          })}

          <button
            type="button"
            onClick={addStep}
            className="flex items-center gap-1 rounded-md border border-dashed px-2 py-1 text-xs text-muted-foreground hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            <Plus className="h-3 w-3" /> Add step
          </button>
        </div>

        {/* Revise feedback */}
        <div className="px-4 pb-2">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
            placeholder="Optional: describe changes to request a revised plan"
            className="w-full resize-y rounded-md border bg-background px-2 py-1 text-xs dark:border-slate-600"
          />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 border-t px-4 py-3 dark:border-slate-700">
          <Button
            size="sm"
            onClick={() => submit("accept")}
            disabled={submitting || enabledCount === 0}
            className="gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
          >
            <Check className="h-3.5 w-3.5" />
            Accept & run
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => submit("revise")}
            disabled={submitting || !feedback.trim()}
            className="gap-1.5"
            title={!feedback.trim() ? "Describe the changes first" : "Request a revised plan"}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Request changes
          </Button>
        </div>
      </div>
    </div>
  );
}
