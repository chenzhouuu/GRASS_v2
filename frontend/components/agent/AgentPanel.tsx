"use client";

import { useAgentStore } from "@/stores/agentStore";
import { useChatStore } from "@/stores/chatStore";
import { AgentFlowTimeline } from "./AgentFlowTimeline";
import { EmptyState } from "@/components/shared/EmptyState";
import { Workflow, Clock } from "lucide-react";
import type { PipelineRun } from "@/lib/types";

function formatElapsed(ms: number | null): string {
  if (ms === null) return "...";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function PipelineView({ pipeline, isLive }: { pipeline: PipelineRun; isLive: boolean }) {
  const isStreaming = useChatStore((s) => s.isStreaming);
  const expandedSteps = useAgentStore((s) => s.expandedSteps);
  const toggleExpanded = useAgentStore((s) => s.toggleExpanded);

  const elapsed = isLive && isStreaming
    ? null
    : pipeline.totalDuration;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b px-4 py-3">
        <p className="text-base font-medium truncate">{pipeline.query}</p>
        <div className="flex items-center gap-3 mt-1">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {formatElapsed(elapsed)}
          </span>
          <span className="text-xs text-muted-foreground">
            {pipeline.steps.filter((s) => s.status === "done").length}/{pipeline.steps.length} steps
          </span>
        </div>
      </div>

      <div
        className="min-h-0 flex-1 overflow-y-auto px-3 py-3 space-y-3 scrollbar-thin"
        style={{ scrollbarGutter: "stable" }}
      >
        <AgentFlowTimeline
          steps={pipeline.steps}
          expandedSteps={expandedSteps}
          onToggle={toggleExpanded}
        />
      </div>
    </div>
  );
}

export function AgentPanel() {
  const livePipeline = useAgentStore((s) => s.livePipeline);
  const pipelineHistory = useAgentStore((s) => s.pipelineHistory);

  if (livePipeline) {
    return <PipelineView pipeline={livePipeline} isLive />;
  }

  const historyEntries = Object.values(pipelineHistory);
  if (historyEntries.length > 0) {
    const mostRecent = historyEntries.reduce((a, b) =>
      (a.startedAt > b.startedAt ? a : b),
    );
    return <PipelineView pipeline={mostRecent} isLive={false} />;
  }

  return (
    <EmptyState
      icon={<Workflow className="h-10 w-10" />}
      title="Agent Pipeline"
      subtitle="Send a message to see the agent execution details"
    />
  );
}
