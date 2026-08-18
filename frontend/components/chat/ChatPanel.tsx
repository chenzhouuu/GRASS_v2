"use client";

import { useCallback, useEffect } from "react";
import { Circle, Menu } from "lucide-react";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { WelcomePage } from "./WelcomePage";
import { sendChatMessage } from "@/lib/api";
import { stopRunWatch } from "@/lib/runWatch";
import { useAppStore } from "@/stores/appStore";
import { useChatStore } from "@/stores/chatStore";
import { useSettingsStore } from "@/stores/settingsStore";

export function ChatPanel() {
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const sessions = useAppStore((s) => s.sessions);
  const neo4jConnected = useAppStore((s) => s.neo4jConnected);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const agentModels = useSettingsStore((s) => s.agentModels);
  const messages = useChatStore((s) => s.messages);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const supervisorModel = agentModels.Supervisor?.model ?? "GPT-4o";
  const hasMessages = messages.length > 0;

  useEffect(() => {
    return () => {
      // Unmounting means "stop WATCHING", deliberately not "stop the run":
      // the backend owns the run and finishes + persists it regardless.
      // Stopping a run is only ever the explicit Stop button (stopActiveRun).
      stopRunWatch();
    };
  }, []);

  const handleSend = useCallback(async (content: string) => {
    // sendChatMessage registers the new watch itself (closing the previous
    // one) — closing a watch never cancels the run it was observing.
    await sendChatMessage(content, currentSessionId ?? undefined);
  }, [currentSessionId]);

  // ── Welcome page (no messages yet) ─────────────────────────────────────────
  if (!hasMessages) {
    return (
      <div className="flex h-full min-h-0 flex-col" data-tour="chat-panel">
        {/* Minimal mobile header */}
        <div className="flex shrink-0 items-center justify-between px-6 py-3 md:hidden">
          <button onClick={toggleSidebar} className="rounded p-1 hover:bg-muted">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs">
              <Circle className={`h-2 w-2 ${neo4jConnected ? "fill-success text-success" : "fill-warning text-warning"}`} />
              {neo4jConnected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </div>

        <WelcomePage onSend={handleSend} />
      </div>
    );
  }

  // ── Active conversation ────────────────────────────────────────────────────
  return (
    <div className="flex h-full min-h-0 flex-col" data-tour="chat-panel">
      {/* ── Chat header ─────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={toggleSidebar} className="md:hidden rounded p-1 hover:bg-muted">
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold truncate">
              {currentSession?.title ?? "New Chat"}
            </h1>
            <p className="text-xs text-muted-foreground">
              Session · {messages.length} message{messages.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs">
            <Circle className={`h-2 w-2 ${neo4jConnected ? "fill-success text-success" : "fill-warning text-warning"}`} />
            {neo4jConnected ? "Connected" : "Disconnected"}
          </span>
          <span className="rounded-full border bg-info-bg px-2.5 py-1 text-2xs text-info">
            {supervisorModel}
          </span>
        </div>
      </div>

      <MessageList onSendMessage={handleSend} />
      <ChatInput onSend={handleSend} />
    </div>
  );
}
