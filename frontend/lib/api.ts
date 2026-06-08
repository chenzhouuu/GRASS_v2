import { useChatStore } from "@/stores/chatStore";
import { useMapStore } from "@/stores/mapStore";
import { useAgentStore } from "@/stores/agentStore";
import { useAppStore } from "@/stores/appStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { connectSSE } from "./sse";
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

    // 4. Connect SSE to stream events for this run
    const disconnect = connectSSE(run_id, assistantId);
    return disconnect;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Network error";
    store.updateMessage(assistantId, { content: `Error: ${msg}` });
    useAgentStore.getState().discardLivePipeline();
    store.setStreaming(false);
  }
}
