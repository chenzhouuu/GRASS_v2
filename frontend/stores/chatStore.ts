import { create } from "zustand";
import type {
  Message,
  AgentStatus,
  AgentName,
  AgentStatusValue,
  GRASSPlan,
  PlanDecision,
} from "@/lib/types";

interface ChatState {
  // ── Messages ────────────────────────────────────────────────────────────
  messages: Message[];
  addMessage: (message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  clearMessages: () => void;

  // ── Streaming ───────────────────────────────────────────────────────────
  isStreaming: boolean;
  currentRunId: string | null;
  currentAgent: AgentName | null;
  agentProgress: AgentStatus[];

  setStreaming: (streaming: boolean, runId?: string | null) => void;
  setStreamingAgent: (agent: AgentName | null, status?: AgentStatusValue) => void;
  updateAgentStatus: (agent: AgentName, status: AgentStatusValue, extra?: Partial<AgentStatus>) => void;
  resetAgentProgress: () => void;

  // ── Plan (human-in-the-loop) ────────────────────────────────────────────
  pendingPlan: GRASSPlan | null;
  planDecision: PlanDecision | null;
  setPendingPlan: (plan: GRASSPlan | null) => void;
  decidePlan: (decision: PlanDecision) => void;

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
  clearMessages: () => set({ messages: [] }),

  // Streaming
  isStreaming: false,
  currentRunId: null,
  currentAgent: null,
  agentProgress: [],

  setStreaming: (streaming, runId = null) =>
    set({ isStreaming: streaming, currentRunId: runId }),
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

  // Plan
  pendingPlan: null,
  planDecision: null,
  setPendingPlan: (plan) => set({ pendingPlan: plan, planDecision: null }),
  decidePlan: (decision) => set({ planDecision: decision, pendingPlan: null }),

  // Input draft
  inputDraft: "",
  setInputDraft: (draft) => set({ inputDraft: draft }),
}));
