"use client";

import { Factory, MapPin, TrendingUp } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";

const EXAMPLES = [
  { icon: Factory, label: "Top 5 processors", query: "What are the top 5 processors by county count?" },
  { icon: MapPin, label: "Show farms on map", query: "Show all farms on the map" },
  { icon: TrendingUp, label: "Optimize transport costs", query: "Optimize transportation costs between farms and processors in PA" },
] as const;

export function ExampleChips() {
  const messageCount = useChatStore((s) => s.messages.length);
  const setInputDraft = useChatStore((s) => s.setInputDraft);

  if (messageCount > 0) return null;

  return (
    <div className="flex flex-wrap justify-center gap-2 px-6 pb-3">
      {EXAMPLES.map((ex) => {
        const Icon = ex.icon;
        return (
          <button
            key={ex.label}
            onClick={() => setInputDraft(ex.query)}
            className="flex items-center gap-2 rounded-lg border bg-card px-3.5 py-2 text-sm text-foreground transition-colors hover:border-primary hover:text-primary"
          >
            <Icon className="h-4 w-4 text-muted-foreground" />
            {ex.label}
          </button>
        );
      })}
    </div>
  );
}
