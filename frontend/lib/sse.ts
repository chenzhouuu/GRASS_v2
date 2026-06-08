import { useChatStore } from "@/stores/chatStore";
import { useMapStore } from "@/stores/mapStore";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useAppStore } from "@/stores/appStore";
import { useAgentStore } from "@/stores/agentStore";
import type {
  AgentName,
  AgentStatus,
  ChartSpecPayload,
  CoPlanStep,
  GeoDataPayload,
  GRASSPlan,
  LedgerProgress,
  MapPayload,
  NvlGraphResult,
  PipelineRun,
  PlanReviewPayload,
  ScenarioComparison,
  StreamAgentName,
  VisualizationData,
} from "@/lib/types";
import { apiUrl } from "@/lib/backend";
import { geoJsonToMapPayload } from "@/lib/mapData";
import { refreshSessionsStore } from "@/hooks/useSessions";

/** Maximum SSE buffer size (1 MB) — prevents OOM from malformed streams. */
const MAX_BUFFER_SIZE = 1024 * 1024;

/**
 * Connects to a Server-Sent Events stream for a given run, parses typed
 * events, and dispatches them to the appropriate Zustand stores.
 *
 * Returns an abort function to close the connection early.
 */
export function connectSSE(
  runId: string,
  assistantMessageId: string,
): () => void {
  const controller = new AbortController();
  const { signal } = controller;

  readStream(runId, assistantMessageId, signal);

  return () => controller.abort();
}

/**
 * Resumes a paused co-planning run with the human's decision and streams the
 * continuation (the POST /api/chat/plan-decision response is itself an SSE
 * stream). Returns an abort function.
 */
export function submitPlanDecision(params: {
  runId: string;
  assistantMessageId: string;
  decision: "accept" | "revise";
  steps?: CoPlanStep[];
  content?: string;
}): () => void {
  const controller = new AbortController();
  resumeRun(params, controller.signal);
  return () => controller.abort();
}

// ─── Internal stream reader ─────────────────────────────────────────────────

async function readStream(
  runId: string,
  assistantMessageId: string,
  signal: AbortSignal,
) {
  let res: Response;
  try {
    res = await fetch(apiUrl(`/api/stream/${runId}`), { signal });
  } catch (err: unknown) {
    if (signal.aborted) return;
    const msg = err instanceof Error ? err.message : "Unknown stream error";
    useChatStore.getState().updateMessage(assistantMessageId, { content: `Error: ${msg}` });
    useChatStore.getState().setStreaming(false);
    return;
  }
  await consumeStream(res, assistantMessageId, signal);
}

async function resumeRun(
  params: {
    runId: string;
    assistantMessageId: string;
    decision: "accept" | "revise";
    steps?: CoPlanStep[];
    content?: string;
  },
  signal: AbortSignal,
) {
  const { runId, assistantMessageId, decision, steps, content } = params;
  const chat = useChatStore.getState();
  chat.setPendingReview(null);
  chat.setStreaming(true, runId);

  let res: Response;
  try {
    res = await fetch(apiUrl("/api/chat/plan-decision"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, decision, steps, content }),
      signal,
    });
  } catch (err: unknown) {
    if (signal.aborted) return;
    const msg = err instanceof Error ? err.message : "Unknown stream error";
    chat.updateMessage(assistantMessageId, { content: `Error: ${msg}` });
    chat.setStreaming(false);
    return;
  }
  await consumeStream(res, assistantMessageId, signal);
}

/** Pump an SSE Response body through the frame parser + dispatcher. */
async function consumeStream(
  res: Response,
  assistantMessageId: string,
  signal: AbortSignal,
) {
  try {
    if (!res.ok || !res.body) {
      useChatStore.getState().updateMessage(assistantMessageId, {
        content: `Error: Stream connection failed (${res.status})`,
      });
      useChatStore.getState().setStreaming(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      if (signal.aborted) return;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      if (buffer.length > MAX_BUFFER_SIZE) {
        console.warn(
          `[SSE] Buffer exceeded ${MAX_BUFFER_SIZE} bytes — truncating to last frame boundary`,
        );
        const lastFrameEnd = buffer.lastIndexOf("\n\n");
        buffer = lastFrameEnd >= 0 ? buffer.slice(lastFrameEnd + 2) : "";
      }

      buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        if (!frame.trim()) continue;
        const parsed = parseSSEFrame(frame);
        if (!parsed) continue;

        dispatch(parsed.event, parsed.data, assistantMessageId);
      }
    }
  } catch (err: unknown) {
    if (signal.aborted) return;
    const msg = err instanceof Error ? err.message : "Unknown stream error";
    useChatStore.getState().updateMessage(assistantMessageId, {
      content: `Error: ${msg}`,
    });
  } finally {
    useChatStore.getState().setStreaming(false);
    // If the run paused at the plan gate, keep the pipeline alive for resume.
    const paused = !!useChatStore.getState().pendingReview;
    const pipeline = useAgentStore.getState().livePipeline;
    if (pipeline && !paused) {
      useAgentStore.getState().completePipeline();
    }
  }
}

// ─── SSE frame parser ───────────────────────────────────────────────────────

function parseSSEFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) return null;

  try {
    const data = JSON.parse(dataLines.join("\n"));
    return { event, data };
  } catch (err) {
    console.warn(
      `[SSE] Failed to parse frame (event="${event}"):`,
      dataLines.join("\n").slice(0, 200),
      err,
    );
    return null;
  }
}

function createSyntheticStepId(agent: string): string {
  return `synthetic:${agent}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function getLatestStep(agent: StreamAgentName) {
  const steps = useAgentStore.getState().livePipeline?.steps ?? [];
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    if (steps[i].agent === agent) return steps[i];
  }
  return null;
}

function toText(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function toAgentProgress(pipeline: PipelineRun | null): AgentStatus[] {
  if (!pipeline) return [];
  return pipeline.steps.map((step) => ({
    agent: step.agent,
    status: step.status,
    message: step.detail.message,
    error: step.detail.error,
  }));
}

// ─── Event dispatcher ───────────────────────────────────────────────────────

function dispatch(
  event: string,
  data: unknown,
  assistantMessageId: string,
) {
  const d = data as Record<string, unknown>;

  switch (event) {
    case "config_applied": {
      const agentModels = d.agent_models as Record<string, { provider: string; model: string }>;
      if (agentModels) {
        const summary = Object.entries(agentModels)
          .map(([name, cfg]) => `${name}: ${cfg.model}`)
          .join(", ");
        console.info("[SSE] Active model config:", summary);
      }
      break;
    }

    case "agent_start": {
      const agentName = d.agent as AgentName;
      const stepId = typeof d.step_id === "string"
        ? d.step_id
        : createSyntheticStepId(agentName);
      const isFirstStep = !(useAgentStore.getState().livePipeline?.steps.length);
      useChatStore.getState().setStreamingAgent(agentName, "running");
      useAgentStore.getState().addAgent(stepId, agentName);
      if (isFirstStep && agentName === "Supervisor") {
        useMapStore.getState().clearMarkers();
        useMapStore.getState().clearLayers();
      }
      break;
    }

    case "agent_complete": {
      const agentName = d.agent as AgentName;
      const stepId = typeof d.step_id === "string"
        ? d.step_id
        : getLatestStep(agentName)?.id;
      useChatStore.getState().updateAgentStatus(agentName, "done", { result: d.result });
      if (stepId) {
        useAgentStore.getState().completeAgent(stepId);
      }
      break;
    }

    case "plan": {
      const plan = data as GRASSPlan;
      useChatStore.getState().updateMessage(assistantMessageId, { plan });
      useAgentStore.getState().setPlan(plan);
      break;
    }

    case "plan_review": {
      // Co-planning gate: surface the editable plan for human review.
      const payload = data as PlanReviewPayload;
      useChatStore.getState().setPendingReview({ payload, assistantMessageId });
      break;
    }

    case "plan_pending": {
      // Graph paused at the gate — stop the spinner; run stays alive for the
      // decision (pendingReview holds run_id). completePipeline is skipped in
      // consumeStream's finally because pendingReview is set.
      useChatStore.getState().setStreaming(false);
      break;
    }

    case "progress": {
      // Live progress-ledger checklist: attach the latest snapshot to the
      // assistant message so the execution timeline renders + persists.
      const progress = data as LedgerProgress;
      useChatStore.getState().updateMessage(assistantMessageId, {
        ledgerProgress: progress,
      });
      useAgentStore.getState().recordEvent("progress");
      break;
    }

    case "scenario_comparison": {
      // What-if before/after: attach the comparison to the assistant message
      // so the ScenarioComparisonCard renders (and persists on reload).
      const comparison = data as ScenarioComparison;
      useChatStore.getState().updateMessage(assistantMessageId, {
        scenarioComparison: comparison,
      });
      useAppStore.getState().setTabBadge("charts", { type: "new" });
      useAgentStore.getState().recordEvent("scenario_comparison");
      break;
    }

    case "cypher_query": {
      useAppStore.getState().setTabBadge("data", { type: "new" });
      const query = d.query as string;
      const rows = (d.results as Record<string, unknown>[]) ?? [];
      const columns = Array.isArray(d.columns) && d.columns.length > 0
        ? (d.columns as string[])
        : rows.length > 0
          ? Object.keys(rows[0])
          : [];

      const db = useDatabaseStore.getState();
      db.setQuery(query);
      const result = {
        query,
        columns,
        rows,
        graph: (d.graph as NvlGraphResult | null | undefined) ?? null,
        graphTruncated: d.graph_truncated as boolean | undefined,
        graphWarnings: (d.graph_warnings as string[] | undefined) ?? [],
      };
      db.setResults(result);
      db.addToHistory(result);

      const agent = useAgentStore.getState();
      agent.recordEvent("cypher_query");
      const cypherStep = getLatestStep("Cypher");
      if (cypherStep) {
        agent.completeAgent(cypherStep.id, {
          ...cypherStep.detail,
          cypherQuery: query,
          cypherPreview: rows.slice(0, 3),
        });
      }
      break;
    }

    case "analysis": {
      const results = d.results;
      if (results) {
        const analyticsStep = getLatestStep("Analytics");
        useAgentStore.getState().recordEvent("analysis");
        if (analyticsStep) {
          useAgentStore.getState().completeAgent(analyticsStep.id, {
            ...analyticsStep.detail,
            message: "Analysis complete",
            codeOutput: toText(results),
          });
        }
      }
      break;
    }

    case "optimization": {
      const status = d.status as string | undefined;
      const solution = d.solution;
      const optimizationStep = getLatestStep("Optimization");
      useAgentStore.getState().recordEvent("optimization");
      if (optimizationStep) {
        useAgentStore.getState().completeAgent(optimizationStep.id, {
          ...optimizationStep.detail,
          message: status ? `Solver status: ${status}` : "Optimization complete",
          ...(solution ? { codeOutput: toText(solution) } : {}),
        });
      }
      if (status) {
        console.info("[SSE] Optimization result status:", status);
      }
      break;
    }

    case "map_data": {
      useAppStore.getState().setTabBadge("map", { type: "new" });
      const payload = data as MapPayload;
      useMapStore.getState().replaceQueryResults(payload.markers ?? [], payload.layers ?? []);
      useChatStore.getState().updateMessage(assistantMessageId, { mapData: payload });
      useAgentStore.getState().recordEvent("map_data");
      break;
    }

    case "chart_spec": {
      useAppStore.getState().setTabBadge("charts", { type: "new" });
      const payload = data as ChartSpecPayload;
      const viz: VisualizationData = {
        id: payload.id,
        type: "chart",
        title:
          typeof payload.spec.layout?.title === "string"
            ? payload.spec.layout.title
            : typeof payload.spec.layout?.title === "object" &&
                payload.spec.layout.title !== null
              ? (payload.spec.layout.title as { text?: string }).text
              : undefined,
        data: payload.spec as unknown as Record<string, unknown>,
      };
      const freshMsg = useChatStore.getState().messages.find(
        (m) => m.id === assistantMessageId,
      );
      const existing = freshMsg?.visualizations ?? [];
      const deduped = existing.some((v) => v.id === viz.id)
        ? existing.map((v) => (v.id === viz.id ? viz : v))
        : [...existing, viz];
      useChatStore.getState().updateMessage(assistantMessageId, {
        visualizations: deduped,
      });
      useAgentStore.getState().recordEvent("chart_spec");
      break;
    }

    case "geo_data": {
      useAppStore.getState().setTabBadge("map", { type: "new" });
      const payload = data as GeoDataPayload;
      const geojson = payload.geojson;
      const mapData = geoJsonToMapPayload(geojson);

      const hasLineStrings = geojson?.features?.some(
        (f) => f.geometry?.type === "LineString",
      );

      const map = useMapStore.getState();
      if (hasLineStrings) {
        map.setRouteGeoJson(geojson);
        map.replaceQueryResults(mapData.markers, []);
      } else {
        map.setRouteGeoJson(null);
        map.replaceQueryResults(mapData.markers, mapData.layers);
      }

      useChatStore.getState().updateMessage(assistantMessageId, { mapData });
      useAgentStore.getState().recordEvent("geo_data");
      break;
    }

    case "report": {
      const url = d.url as string;
      const title = d.title as string | undefined;
      useAppStore.getState().setReport(url, title);
      useAgentStore.getState().recordEvent("report");
      const reportStep = getLatestStep("Report");
      if (reportStep) {
        useAgentStore.getState().completeAgent(reportStep.id, {
          ...reportStep.detail,
          message: title ?? "Report generated",
        });
      }
      break;
    }

    case "response": {
      const markdown = d.markdown as string;
      useChatStore.getState().updateMessage(assistantMessageId, { content: markdown });
      break;
    }

    case "error": {
      const agentName = (d.agent as StreamAgentName | undefined) ?? "System";
      const errorMsg = d.error as string;
      const stepId = typeof d.step_id === "string"
        ? d.step_id
        : getLatestStep(agentName)?.id ?? createSyntheticStepId(agentName);
      if (agentName !== "System") {
        useChatStore.getState().updateAgentStatus(agentName, "error", { error: errorMsg });
      } else {
        useChatStore.getState().updateMessage(assistantMessageId, {
          content: `Error: ${errorMsg}`,
        });
      }
      useAgentStore.getState().failAgent(stepId, agentName, errorMsg);
      break;
    }

    case "done": {
      const pipeline = useAgentStore.getState().livePipeline;
      useChatStore.getState().updateMessage(assistantMessageId, {
        agentProgress: toAgentProgress(pipeline),
      });
      useChatStore.getState().setStreaming(false);

      const events = pipeline?.receivedEvents ?? [];
      useAgentStore.getState().completePipeline();

      const app = useAppStore.getState();
      if (events.includes("geo_data") || events.includes("map_data")) {
        app.autoSwitchTab("map");
      } else if (events.includes("chart_spec")) {
        app.autoSwitchTab("charts");
      } else if (events.includes("cypher_query")) {
        app.autoSwitchTab("data");
      }
      void refreshSessionsStore().catch(() => undefined);
      break;
    }
  }
}

export const __test__ = {
  parseSSEFrame,
  dispatch,
};
