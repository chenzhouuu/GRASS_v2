"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useAgentStore } from "@/stores/agentStore";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { StreamingIndicator } from "./StreamingIndicator";
import { ChevronDown, BarChart3, Loader2 } from "lucide-react";

interface MessageListProps {
  onSendMessage?: (message: string) => void;
}

export function MessageList({ onSendMessage }: MessageListProps) {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const livePipeline = useAgentStore((s) => s.livePipeline);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const currentAgent = [...(livePipeline?.steps ?? [])]
    .reverse()
    .find((step) => step.status === "running")?.agent ?? null;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    function onScroll() {
      if (!container) return;
      const distFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      setShowScrollBtn(distFromBottom > 200);
    }
    container.addEventListener("scroll", onScroll);
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 150;
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isStreaming]);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  if (messages.length === 0) return null;

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto scrollbar-thin"
        style={{ scrollbarGutter: "stable" }}
      >
        <div className="mx-auto flex max-w-[720px] flex-col px-6 py-6">
          {messages.map((message, index) => {
            const isAssistant = message.role === "assistant";
            const isLastMessage = index === messages.length - 1;
            const prevMessage = index > 0 ? messages[index - 1] : null;
            const isTurnSwitch = prevMessage && prevMessage.role !== message.role;

            return (
              <div
                key={message.id}
                className={isTurnSwitch ? "mt-6" : "mt-3"}
              >
                {isStreaming && isLastMessage && isAssistant && !message.content && (
                  <StreamingIndicator />
                )}

                {message.content && (
                  message.role === "user" ? (
                    <UserMessage message={message} />
                  ) : (
                    <AssistantMessage
                      message={message}
                      onSendMessage={onSendMessage}
                    />
                  )
                )}

                {isStreaming && isLastMessage && isAssistant && currentAgent === "Analytics"
                  && (!message.visualizations || message.visualizations.length === 0) && (
                  <div className="mt-4 rounded-xl border bg-muted/30">
                    <div className="flex items-center gap-2 border-b px-4 py-2">
                      <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">Generating chart...</span>
                    </div>
                    <div className="flex h-[200px] items-center justify-center">
                      <BarChart3 className="h-10 w-10 animate-pulse text-muted-foreground/15" />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full border bg-background/90 backdrop-blur-sm px-3 py-1.5 text-sm text-muted-foreground shadow-md hover:text-foreground transition-colors"
          aria-label="Scroll to bottom"
        >
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
