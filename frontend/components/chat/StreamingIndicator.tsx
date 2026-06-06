"use client";

import { useAgentStore } from "@/stores/agentStore";

export function StreamingIndicator() {
  const livePipeline = useAgentStore((s) => s.livePipeline);

  const activeAgents = (livePipeline?.steps ?? [])
    .filter((step) => step.status === "running" || step.status === "done")
    .map((step) => step.agent);

  const currentAgent = [...(livePipeline?.steps ?? [])]
    .reverse()
    .find((step) => step.status === "running")?.agent ?? null;

  return (
    <div className="flex items-center gap-3 py-1">
      <div className="flex items-center gap-1">
        <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />
        <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />
        <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />
      </div>
      <span className="text-sm text-muted-foreground">
        {currentAgent ? `${currentAgent} working...` : "Thinking..."}
      </span>
      {activeAgents.length > 1 && (
        <span className="rounded-md bg-accent-subtle px-2 py-0.5 text-2xs font-medium text-primary">
          {activeAgents.join(" → ")}
        </span>
      )}
    </div>
  );
}
