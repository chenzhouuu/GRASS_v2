import { create } from "zustand";
import type {
  AgentCardDetail,
  AgentPipelineStep,
  GRASSPlan,
  PipelineRun,
  PlanDecision,
  StreamAgentName,
} from "@/lib/types";

const MAX_PIPELINE_HISTORY = 50;

interface AgentState {
  livePipeline: PipelineRun | null;
  pipelineHistory: Record<string, PipelineRun>; // keyed by messageId
  expandedSteps: Record<string, boolean>;

  // Actions
  startPipeline: (messageId: string, query: string) => void;
  addAgent: (stepId: string, agent: StreamAgentName) => void;
  completeAgent: (stepId: string, detail?: AgentCardDetail) => void;
  failAgent: (stepId: string, agent: StreamAgentName, error: string) => void;
  setPlan: (plan: GRASSPlan) => void;
  setPlanDecision: (decision: PlanDecision) => void;
  completePipeline: () => void;
  discardLivePipeline: () => void;
  recordEvent: (eventType: string) => void;
  toggleExpanded: (stepId: string) => void;
  reset: () => void;
}

function makeStep(stepId: string, agent: StreamAgentName): AgentPipelineStep {
  return {
    id: stepId,
    agent,
    status: "running",
    startedAt: Date.now(),
    completedAt: null,
    duration: null,
    detail: {},
  };
}

function updateStep(
  steps: AgentPipelineStep[],
  stepId: string,
  patch: Partial<AgentPipelineStep>,
): AgentPipelineStep[] {
  return steps.map((step) => (step.id === stepId ? { ...step, ...patch } : step));
}

export const useAgentStore = create<AgentState>((set) => ({
  livePipeline: null,
  pipelineHistory: {},
  expandedSteps: {},

  startPipeline: (messageId, query) =>
    set({
      livePipeline: {
        messageId,
        query,
        steps: [],
        plan: null,
        planDecision: null,
        startedAt: Date.now(),
        completedAt: null,
        totalDuration: null,
        receivedEvents: [],
      },
    }),

  addAgent: (stepId, agent) =>
    set((s) => {
      if (!s.livePipeline) return s;
      const existing = s.livePipeline.steps.find((step) => step.id === stepId);
      if (existing) {
        return {
          livePipeline: {
            ...s.livePipeline,
            steps: updateStep(s.livePipeline.steps, stepId, {
              status: "running",
              startedAt: Date.now(),
              completedAt: null,
              duration: null,
            }),
          },
        };
      }
      return {
        livePipeline: {
          ...s.livePipeline,
          steps: [...s.livePipeline.steps, makeStep(stepId, agent)],
        },
      };
    }),

  completeAgent: (stepId, detail) =>
    set((s) => {
      if (!s.livePipeline) return s;
      const step = s.livePipeline.steps.find((st) => st.id === stepId);
      if (!step) return s;
      const now = Date.now();
      const duration = step.startedAt ? now - step.startedAt : null;
      return {
        livePipeline: {
          ...s.livePipeline,
          steps: updateStep(s.livePipeline.steps, stepId, {
            status: "done",
            completedAt: now,
            duration,
            ...(detail ? { detail: { ...step.detail, ...detail } } : {}),
          }),
        },
      };
    }),

  failAgent: (stepId, agent, error) =>
    set((s) => {
      if (!s.livePipeline) return s;
      const step = s.livePipeline.steps.find((st) => st.id === stepId);
      const now = Date.now();
      if (!step) {
        return {
          livePipeline: {
            ...s.livePipeline,
            steps: [
              ...s.livePipeline.steps,
              {
                id: stepId,
                agent,
                status: "error",
                startedAt: now,
                completedAt: now,
                duration: 0,
                detail: { error },
              },
            ],
          },
        };
      }
      const duration = step.startedAt ? now - step.startedAt : null;
      return {
        livePipeline: {
          ...s.livePipeline,
          steps: updateStep(s.livePipeline.steps, stepId, {
            status: "error",
            completedAt: now,
            duration,
            detail: { ...step.detail, error },
          }),
        },
      };
    }),

  setPlan: (plan) =>
    set((s) => {
      if (!s.livePipeline) return s;
      return {
        livePipeline: { ...s.livePipeline, plan },
      };
    }),

  setPlanDecision: (decision) =>
    set((s) => {
      if (!s.livePipeline) return s;
      return {
        livePipeline: { ...s.livePipeline, planDecision: decision },
      };
    }),

  completePipeline: () =>
    set((s) => {
      if (!s.livePipeline) return s;
      const now = Date.now();
      const completed: PipelineRun = {
        ...s.livePipeline,
        completedAt: now,
        totalDuration: now - s.livePipeline.startedAt,
      };
      let history = {
        ...s.pipelineHistory,
        [completed.messageId]: completed,
      };
      const keys = Object.keys(history);
      if (keys.length > MAX_PIPELINE_HISTORY) {
        const sorted = keys.sort(
          (a, b) => (history[a].startedAt ?? 0) - (history[b].startedAt ?? 0),
        );
        const toRemove = sorted.slice(0, keys.length - MAX_PIPELINE_HISTORY);
        history = { ...history };
        for (const key of toRemove) {
          delete history[key];
        }
      }
      return {
        livePipeline: null,
        pipelineHistory: history,
      };
    }),

  discardLivePipeline: () =>
    set((s) => ({
      ...s,
      livePipeline: null,
    })),

  recordEvent: (eventType) =>
    set((s) => {
      if (!s.livePipeline) return s;
      if (s.livePipeline.receivedEvents.includes(eventType)) return s;
      return {
        livePipeline: {
          ...s.livePipeline,
          receivedEvents: [...s.livePipeline.receivedEvents, eventType],
        },
      };
    }),

  toggleExpanded: (stepId) =>
    set((s) => ({
      expandedSteps: {
        ...s.expandedSteps,
        [stepId]: !s.expandedSteps[stepId],
      },
    })),

  reset: () => set({ livePipeline: null, pipelineHistory: {}, expandedSteps: {} }),
}));
