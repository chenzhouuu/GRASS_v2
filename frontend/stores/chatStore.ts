import { create } from "zustand";
import type {
  Message,
  AgentStatus,
  AgentName,
  AgentStatusValue,
  GRASSPlan,
  PlanDecision,
  PlanReviewPayload,
} from "@/lib/types";

interface ChatState {
  // ── Messages ────────────────────────────────────────────────────────────
  messages: Message[];
  addMessage: (message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  removeMessage: (id: string) => void;
  clearMessages: () => void;

  // ── Streaming ───────────────────────────────────────────────────────────
  isStreaming: boolean;
  currentRunId: string | null;
  currentAgent: AgentName | null;
  agentProgress: AgentStatus[];

  setStreaming: (streaming: boolean, runId?: string | null) => void;
  // Event-id cursor of the run being watched — sent as Last-Event-ID when
  // re-attaching to the same run after a dropped connection.
  lastEventId: string | null;
  lastEventRunId: string | null;
  setLastEvent: (runId: string, eventId: string) => void;
  setStreamingAgent: (agent: AgentName | null, status?: AgentStatusValue) => void;
  updateAgentStatus: (agent: AgentName, status: AgentStatusValue, extra?: Partial<AgentStatus>) => void;
  resetAgentProgress: () => void;

  // ── Plan (legacy read-only plan event) ──────────────────────────────────
  pendingPlan: GRASSPlan | null;
  planDecision: PlanDecision | null;
  setPendingPlan: (plan: GRASSPlan | null) => void;
  decidePlan: (decision: PlanDecision) => void;

  // ── Co-planning mode (human approval gate) ───────────────────────────────
  planMode: boolean;                       // user toggle: send mode="plan"
  setPlanMode: (on: boolean) => void;
  // The active gate awaiting a decision, tied to its assistant message.
  pendingReview: { payload: PlanReviewPayload; assistantMessageId: string } | null;
  setPendingReview: (
    review: { payload: PlanReviewPayload; assistantMessageId: string } | null,
  ) => void;

  // ── Input draft ─────────────────────────────────────────────────────────
  inputDraft: string;
  setInputDraft: (draft: string) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  // Messages
  messages: [],
  addMessage: (message) =>
    set((s) => ({ messages: [...s.messages, message] })),
  updateMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  removeMessage: (id) =>
    set((s) => ({ messages: s.messages.filter((m) => m.id !== id) })),
  clearMessages: () => set({ messages: [] }),

  // Streaming
  isStreaming: false,
  currentRunId: null,
  currentAgent: null,
  agentProgress: [],

  setStreaming: (streaming, runId = null) =>
    set({ isStreaming: streaming, currentRunId: runId }),
  lastEventId: null,
  lastEventRunId: null,
  setLastEvent: (runId, eventId) =>
    set({ lastEventRunId: runId, lastEventId: eventId }),
  setStreamingAgent: (agent, status = "running") =>
    set((s) => {
      if (!agent) return { currentAgent: null };
      const existing = s.agentProgress.find((a) => a.agent === agent);
      if (existing) {
        return {
          currentAgent: agent,
          agentProgress: s.agentProgress.map((a) =>
            a.agent === agent ? { ...a, status } : a
          ),
        };
      }
      return {
        currentAgent: agent,
        agentProgress: [...s.agentProgress, { agent, status }],
      };
    }),
  updateAgentStatus: (agent, status, extra) =>
    set((s) => {
      const exists = s.agentProgress.some((a) => a.agent === agent);
      if (exists) {
        return {
          agentProgress: s.agentProgress.map((a) =>
            a.agent === agent ? { ...a, status, ...extra } : a
          ),
        };
      }
      return {
        agentProgress: [...s.agentProgress, { agent, status, ...extra }],
      };
    }),
  resetAgentProgress: () =>
    set({ agentProgress: [], currentAgent: null }),

  // Plan (legacy)
  pendingPlan: null,
  planDecision: null,
  setPendingPlan: (plan) => set({ pendingPlan: plan, planDecision: null }),
  decidePlan: (decision) => set({ planDecision: decision, pendingPlan: null }),

  // Co-planning mode
  planMode: false,
  setPlanMode: (on) => set({ planMode: on }),
  pendingReview: null,
  setPendingReview: (review) => set({ pendingReview: review }),

  // Input draft
  inputDraft: "",
  setInputDraft: (draft) => set({ inputDraft: draft }),
}));
