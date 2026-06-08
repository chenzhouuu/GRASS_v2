"use client";

import { useRef, useCallback, useEffect, useState } from "react";
import { ArrowUp, MapPin, X } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useMapStore } from "@/stores/mapStore";
import { cn } from "@/lib/utils";
import { PlanModeToggle } from "./PlanModeToggle";

interface ChatInputProps {
  onSend: (content: string) => void;
}

export function ChatInput({ onSend }: ChatInputProps) {
  const inputDraft = useChatStore((s) => s.inputDraft);
  const setInputDraft = useChatStore((s) => s.setInputDraft);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);
  const clearSelectedRegion = useMapStore((s) => s.clearSelectedRegion);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isMac, setIsMac] = useState(false);

  useEffect(() => {
    setIsMac(navigator.platform?.includes("Mac") ?? false);
  }, []);

  // Auto-resize textarea to content (up to ~6 lines)
  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  useEffect(() => {
    resize();
  }, [inputDraft, resize]);

  const handleSend = useCallback(() => {
    const trimmed = inputDraft.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setInputDraft("");
    requestAnimationFrame(() => {
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    });
  }, [inputDraft, isStreaming, onSend, setInputDraft]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div className="border-t px-6 py-4">
      <div className="mx-auto max-w-[720px]">
        {/* Region focus badge */}
        {selectedRegionBbox && (
          <div className="mb-2 flex items-center gap-2 rounded-md border border-primary/30 bg-accent-subtle px-2.5 py-1.5 text-sm text-primary">
            <MapPin className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              Region focus: <span className="font-mono text-xs">{selectedRegionBbox}</span>
            </span>
            <button
              type="button"
              onClick={clearSelectedRegion}
              className="ml-auto rounded p-0.5 hover:bg-primary/10"
              title="Clear region focus"
              aria-label="Clear region focus"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Input box */}
        <div className={cn(
          "flex items-end gap-2 rounded-xl border-2 px-3 py-3",
          "border-border-strong focus-within:border-primary transition-colors"
        )}>
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputDraft}
            onChange={(e) => setInputDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your supply chain data..."
            disabled={isStreaming}
            className={cn(
              "flex-1 resize-none bg-transparent text-base outline-none",
              "placeholder:text-muted-foreground",
              "disabled:cursor-not-allowed disabled:opacity-50",
              "scrollbar-thin"
            )}
          />

          {/* Shortcut label */}
          <kbd className="pointer-events-none hidden select-none self-center rounded border bg-muted px-1.5 py-0.5 text-2xs text-muted-foreground sm:inline">
            {isMac ? "⌘" : "Ctrl"}↩
          </kbd>

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={!inputDraft.trim() || isStreaming}
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
              "bg-primary text-primary-foreground",
              "hover:bg-accent-hover",
              "disabled:bg-muted disabled:text-muted-foreground disabled:cursor-not-allowed"
            )}
            aria-label="Send message"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>

        {/* Composer action row */}
        <div className="mt-2 flex items-center">
          <PlanModeToggle />
        </div>
      </div>
    </div>
  );
}
