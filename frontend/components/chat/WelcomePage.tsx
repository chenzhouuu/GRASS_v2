"use client";

import { useCallback, useRef, useEffect, useState } from "react";
import { ArrowUp, MapPin, X } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useMapStore } from "@/stores/mapStore";
import { cn } from "@/lib/utils";
import { PlanModeToggle } from "./PlanModeToggle";

// ─── Suggestions (text-only, like Claude/ChatGPT) ────────────────────────────

const SUGGESTIONS = [
  "Top 5 dairy processors by volume",
  "Show all farms on the map",
  "Optimize transport costs in PA",
  "Milk supply by cooperative",
] as const;

// ─── Greeting based on time of day ───────────────────────────────────────────

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// ─── Component ───────────────────────────────────────────────────────────────

interface WelcomePageProps {
  onSend: (content: string) => void;
}

export function WelcomePage({ onSend }: WelcomePageProps) {
  const setInputDraft = useChatStore((s) => s.setInputDraft);
  const inputDraft = useChatStore((s) => s.inputDraft);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const selectedRegionBbox = useMapStore((s) => s.selectedRegionBbox);
  const clearSelectedRegion = useMapStore((s) => s.clearSelectedRegion);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isMac, setIsMac] = useState(false);

  useEffect(() => {
    setIsMac(navigator.platform?.includes("Mac") ?? false);
  }, []);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  useEffect(() => { resize(); }, [inputDraft, resize]);

  const handleSend = useCallback(() => {
    const trimmed = inputDraft.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setInputDraft("");
  }, [inputDraft, isStreaming, onSend, setInputDraft]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex h-full min-h-0 flex-col items-center">
      {/* ── Scrollable content ─────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 w-full flex-col items-center justify-center overflow-y-auto px-6 py-12">
        <div className="flex w-full max-w-[560px] flex-col items-center">

          {/* ── Logo ──────────────────────────────────────────────── */}
          <div className="relative mb-8">
            <div className="absolute inset-0 -m-3 rounded-full bg-primary/6 blur-2xl" />
            <img
              src="/GRASS_logo.png"
              alt="GRASS"
              className="relative h-16 w-16 rounded-full object-cover ring-1 ring-border"
            />
          </div>

          {/* ── Greeting ──────────────────────────────────────────── */}
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {getGreeting()}
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            What would you like to explore?
          </p>

          {/* ── Suggestions ───────────────────────────────────────── */}
          <div className="mt-8 grid w-full grid-cols-2 gap-2">
            {SUGGESTIONS.map((text) => (
              <button
                key={text}
                onClick={() => onSend(text)}
                className={cn(
                  "rounded-xl border px-4 py-3 text-left text-sm text-foreground transition-all",
                  "hover:border-primary/40 hover:bg-accent-subtle",
                  "active:scale-[0.98]",
                )}
              >
                {text}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Input area (pinned to bottom) ──────────────────────────── */}
      <div className="w-full shrink-0 border-t px-6 py-4">
        <div className="mx-auto max-w-[560px]">
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
                aria-label="Clear region focus"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          <div className={cn(
            "flex items-end gap-2 rounded-xl border-2 px-3 py-3",
            "border-border-strong focus-within:border-primary transition-colors",
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
                "scrollbar-thin",
              )}
            />
            <kbd className="pointer-events-none hidden select-none self-center rounded border bg-muted px-1.5 py-0.5 text-2xs text-muted-foreground sm:inline">
              {isMac ? "⌘" : "Ctrl"}↩
            </kbd>
            <button
              onClick={handleSend}
              disabled={!inputDraft.trim() || isStreaming}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
                "bg-primary text-primary-foreground",
                "hover:bg-accent-hover",
                "disabled:bg-muted disabled:text-muted-foreground disabled:cursor-not-allowed",
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
    </div>
  );
}
