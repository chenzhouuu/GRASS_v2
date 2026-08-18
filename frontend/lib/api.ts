import { toast } from "sonner";

import { useChatStore } from "@/stores/chatStore";
import { useMapStore } from "@/stores/mapStore";
import { useAgentStore } from "@/stores/agentStore";
import { useAppStore } from "@/stores/appStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { connectSSE } from "./sse";
import { setRunWatch } from "./runWatch";
import type { Message } from "./types";
import { apiUrl } from "./backend";
import { createSession, refreshSessionsStore } from "@/hooks/useSessions";

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

// ─── Chat ───────────────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string;
  session_id?: string;
  region_bbox?: string;
  mode?: string;
}

interface ChatResponse {
  run_id: string;
  session_id: string;
}

/**
 * Sends a user message, creates an empty assistant message placeholder,
 * starts SSE streaming, and returns the cleanup function.
 */
export async function sendChatMessage(content: string, sessionId?: string) {
  const store = useChatStore.getState();
  const regionBbox = useMapStore.getState().selectedRegionBbox ?? undefined;
  let activeSessionId = sessionId ?? useAppStore.getState().currentSessionId ?? undefined;

  // 1. Add user message to store
  const userMsg: Message = {
    id: makeId(),
    role: "user",
    content,
    timestamp: Date.now(),
  };
  store.addMessage(userMsg);

  // 2. Create assistant placeholder
  const assistantId = makeId();
  const assistantMsg: Message = {
    id: assistantId,
    role: "assistant",
    content: "",
    timestamp: Date.now(),
  };
  store.addMessage(assistantMsg);

  // 3. POST to /api/chat to initiate the run
  store.setStreaming(true);
  store.resetAgentProgress();
  useAgentStore.getState().startPipeline(assistantId, content);
  useAppStore.getState().setActiveRightTab("agent");

  try {
    if (!activeSessionId) {
      const session = await createSession();
      activeSessionId = session.id;
    }

    await useSettingsStore.getState().saveSessionModelConfig(activeSessionId);

    const res = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: content,
        session_id: activeSessionId,
        region_bbox: regionBbox,
        mode: useChatStore.getState().planMode ? "plan" : "direct",
      } satisfies ChatRequest),
    });

    if (res.status === 409) {
      // The session already has a run executing (second tab, race with a
      // reconnect). The backend rejected BEFORE persisting anything, so
      // undo the optimistic messages and give the draft back.
      store.removeMessage(userMsg.id);
      store.removeMessage(assistantId);
      useAgentStore.getState().discardLivePipeline();
      store.setStreaming(false);
      if (!useChatStore.getState().inputDraft.trim()) {
        store.setInputDraft(content);
      }
      toast.warning("This session already has a task running", {
        description:
          "Wait for it to finish or press Stop, then send again. Your message was kept in the input box.",
      });
      return;
    }

    if (!res.ok) {
      const errText = await res.text().catch(() => "Unknown error");
      store.updateMessage(assistantId, {
        content: `Error: Failed to send message (${res.status}): ${errText}`,
      });
      useAgentStore.getState().discardLivePipeline();
      store.setStreaming(false);
      return;
    }

    const { run_id, session_id } = (await res.json()) as ChatResponse;
    useAppStore.getState().setCurrentSession(session_id);

    try {
      await refreshSessionsStore();
    } catch {
      const existing = useAppStore.getState().sessions.some((s) => s.id === session_id);
      if (!existing) {
        useAppStore.getState().addSession({
          id: session_id,
          title: "New Session",
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messageCount: 0,
          lastMessagePreview: content.slice(0, 120),
        });
      }
    }

    store.setStreaming(true, run_id);

    // 4. Watch the run. The watch handle only closes this client's SSE
    // connection — the backend owns the run and finishes it regardless.
    const disconnect = connectSSE(run_id, assistantId);
    setRunWatch(disconnect);
    return disconnect;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Network error";
    store.updateMessage(assistantId, { content: `Error: ${msg}` });
    useAgentStore.getState().discardLivePipeline();
    store.setStreaming(false);
  }
}

// ─── Backend-owned runs: discovery and explicit stop ────────────────────────

interface ActiveRunInfo {
  run_id: string;
  status: "running" | "awaiting_plan";
  last_event_id: string;
}

/**
 * If the session has a run in flight (page refresh, second tab), attach a
 * fresh assistant placeholder and watch it. The full backlog is replayed, so
 * charts, plan cards, and the answer rebuild exactly as a live viewer saw
 * them. Returns quietly when there is nothing to re-attach to.
 */
export async function reconnectToActiveRun(sessionId: string): Promise<void> {
  let active: ActiveRunInfo | null;
  try {
    const res = await fetch(apiUrl(`/api/sessions/${sessionId}/active-run`));
    if (!res.ok) return;
    active = (await res.json()) as ActiveRunInfo | null;
  } catch {
    return;
  }
  if (!active?.run_id) return;

  const store = useChatStore.getState();
  const assistantId = makeId();
  store.addMessage({
    id: assistantId,
    role: "assistant",
    content: "",
    timestamp: Date.now(),
  });

  const lastUserMessage = [...store.messages]
    .reverse()
    .find((m) => m.role === "user");
  useAgentStore.getState().startPipeline(assistantId, lastUserMessage?.content ?? "");
  // For an awaiting_plan run the replayed plan_pending event turns the
  // spinner off again and surfaces the review card.
  store.setStreaming(true, active.run_id);
  setRunWatch(connectSSE(active.run_id, assistantId));
}

/**
 * Explicitly stop the run being watched. This is the ONLY way a client ends
 * a run — disconnecting/refreshing never does. The backend persists the
 * partial answer; the session is reloaded so the transcript shows it.
 */
export async function stopActiveRun(): Promise<void> {
  const runId = useChatStore.getState().currentRunId;
  if (!runId) return;
  try {
    await fetch(apiUrl(`/api/chat/${runId}/stop`), { method: "POST" });
  } catch {
    return; // backend unreachable — leave the watch as-is
  }
  // The cancel path publishes done through the stream, which closes out the
  // watching view; refresh the session list so previews update.
  void refreshSessionsStore().catch(() => undefined);
}
