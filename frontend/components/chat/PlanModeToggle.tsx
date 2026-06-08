"use client";

import { ListChecks } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { cn } from "@/lib/utils";

/**
 * Composer mode pill: toggles co-planning ("Plan") mode. When on, the next
 * query is drafted into an editable plan and paused for review before it runs.
 * Shared by the welcome composer and the in-conversation input so the control
 * is available both before and after the first message.
 */
export function PlanModeToggle({ className }: { className?: string }) {
  const planMode = useChatStore((s) => s.planMode);
  const setPlanMode = useChatStore((s) => s.setPlanMode);

  return (
    <button
      type="button"
      onClick={() => setPlanMode(!planMode)}
      aria-pressed={planMode}
      title="Plan mode: review and edit a step-by-step plan before it runs"
      className={cn(
        "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        planMode
          ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
          : "border-border text-muted-foreground hover:bg-muted",
        className,
      )}
    >
      <ListChecks className="h-3.5 w-3.5" />
      Plan{planMode ? " · on" : ""}
    </button>
  );
}
