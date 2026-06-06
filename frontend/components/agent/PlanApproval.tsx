"use client";

import { useState, useCallback } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useAgentStore } from "@/stores/agentStore";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiUrl } from "@/lib/backend";
import type { GRASSPlan, PlanStep, PlanDecision } from "@/lib/types";
import {
  ClipboardList,
  Check,
  Pencil,
  X,
  GripVertical,
  Trash2,
  ArrowUp,
  ArrowDown,
} from "lucide-react";

interface PlanApprovalProps {
  plan: GRASSPlan;
  messageId: string;
  decision?: PlanDecision | null;
}

const intentColors: Record<string, string> = {
  analytical: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  spatial: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  factual_lookup: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  optimization: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  report: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  conversational: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
};

export function PlanApproval({ plan, messageId, decision: existingDecision }: PlanApprovalProps) {
  const decidePlan = useChatStore((s) => s.decidePlan);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const currentRunId = useChatStore((s) => s.currentRunId);
  const setPlanDecision = useAgentStore((s) => s.setPlanDecision);

  const [isModifying, setIsModifying] = useState(false);
  const [editedSteps, setEditedSteps] = useState<PlanStep[]>(plan.steps);
  const [submitting, setSubmitting] = useState(false);

  const isDecided = !!existingDecision;

  const sendDecision = useCallback(
    async (decision: PlanDecision, steps?: PlanStep[]) => {
      setSubmitting(true);
      try {
        await fetch(apiUrl("/api/chat/plan-decision"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            run_id: currentRunId,
            decision,
            steps: steps ?? plan.steps,
          }),
        });
        decidePlan(decision);
        setPlanDecision(decision);
        updateMessage(messageId, { planDecision: decision });
      } finally {
        setSubmitting(false);
      }
    },
    [currentRunId, decidePlan, setPlanDecision, messageId, plan.steps, updateMessage],
  );

  const handleApprove = useCallback(() => sendDecision("approved"), [sendDecision]);
  const handleModifyConfirm = useCallback(() => {
    sendDecision("modified", editedSteps);
    setIsModifying(false);
  }, [editedSteps, sendDecision]);
  const handleCancel = useCallback(() => sendDecision("cancelled"), [sendDecision]);

  const moveStep = useCallback(
    (index: number, direction: -1 | 1) => {
      const target = index + direction;
      if (target < 0 || target >= editedSteps.length) return;
      const next = [...editedSteps];
      [next[index], next[target]] = [next[target], next[index]];
      setEditedSteps(next);
    },
    [editedSteps],
  );

  const removeStep = useCallback(
    (index: number) => setEditedSteps((s) => s.filter((_, i) => i !== index)),
    [],
  );

  const intentColor = intentColors[plan.intent] ?? intentColors.conversational;
  const stepsToShow = isModifying ? editedSteps : plan.steps;

  const decisionBadge = existingDecision && (
    <span
      className={cn(
        "ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        existingDecision === "approved" && "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
        existingDecision === "modified" && "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
        existingDecision === "cancelled" && "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
      )}
    >
      {existingDecision}
    </span>
  );

  return (
    <div
      className={cn(
        "w-full rounded-xl border shadow-sm",
        "bg-gradient-to-br from-slate-50 to-slate-100/80",
        "dark:from-slate-900 dark:to-slate-800/80 dark:border-slate-700",
        isDecided && "opacity-80",
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-3 dark:border-slate-700">
        <ClipboardList className="h-4 w-4 text-emerald-600" />
        <span className="text-sm font-semibold">Execution Plan</span>
        {decisionBadge}
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Intent + summary */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Intent:</span>
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", intentColor)}>
            {plan.intent.replace(/_/g, " ")}
          </span>
        </div>
        {plan.summary && <p className="text-xs text-muted-foreground">{plan.summary}</p>}

        {/* Steps */}
        <div className="space-y-1">
          {stepsToShow.map((step, i) => (
            <div
              key={`${step.agent}-${i}`}
              className={cn(
                "group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                isModifying
                  ? "bg-background border dark:border-slate-600"
                  : "bg-white/60 dark:bg-slate-800/60",
              )}
            >
              {isModifying && (
                <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
              )}
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                {i + 1}
              </span>
              <span className="flex-1 truncate">{step.description}</span>
              <span className="shrink-0 rounded bg-slate-200/80 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                {step.agent}
              </span>
              {isModifying && (
                <div className="flex shrink-0 items-center gap-0.5">
                  <button
                    onClick={() => moveStep(i, -1)}
                    disabled={i === 0}
                    className="rounded p-0.5 hover:bg-slate-200 disabled:opacity-30 dark:hover:bg-slate-700"
                  >
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <button
                    onClick={() => moveStep(i, 1)}
                    disabled={i === stepsToShow.length - 1}
                    className="rounded p-0.5 hover:bg-slate-200 disabled:opacity-30 dark:hover:bg-slate-700"
                  >
                    <ArrowDown className="h-3 w-3" />
                  </button>
                  <button
                    onClick={() => removeStep(i)}
                    disabled={stepsToShow.length <= 1}
                    className="rounded p-0.5 text-destructive hover:bg-red-100 disabled:opacity-30 dark:hover:bg-red-900/30"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      {!isDecided && (
        <div className="flex items-center gap-2 border-t px-4 py-3 dark:border-slate-700">
          {isModifying ? (
            <>
              <Button
                size="sm"
                onClick={handleModifyConfirm}
                disabled={submitting || editedSteps.length === 0}
                className="gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                <Check className="h-3.5 w-3.5" />
                Confirm Changes
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditedSteps(plan.steps);
                  setIsModifying(false);
                }}
              >
                Back
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                onClick={handleApprove}
                disabled={submitting}
                className="gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                <Check className="h-3.5 w-3.5" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsModifying(true)}
                disabled={submitting}
                className="gap-1.5 border-amber-300 text-amber-600 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/30"
              >
                <Pencil className="h-3.5 w-3.5" />
                Modify
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleCancel}
                disabled={submitting}
                className="gap-1.5 border-red-300 text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/30"
              >
                <X className="h-3.5 w-3.5" />
                Cancel
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
