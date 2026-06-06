"use client";

import { useCallback } from "react";
import { MapPin, BarChart3, Download, Database, BarChart2, FileText, TrendingUp } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import { useChatStore } from "@/stores/chatStore";
import { cn } from "@/lib/utils";
import type { RightPanelTab } from "@/stores/appStore";

// ── Artifact chips (view existing data) ────────────────────────────────────

interface ArtifactChip {
  label: string;
  icon: React.ElementType;
  tab: RightPanelTab;
}

const ARTIFACT_CHIPS: ArtifactChip[] = [
  { label: "View on Map", icon: MapPin, tab: "map" },
  { label: "Expand Chart", icon: BarChart3, tab: "charts" },
  { label: "View Raw Data", icon: Database, tab: "data" },
];

interface ActionChipsProps {
  hasMap?: boolean;
  hasChart?: boolean;
  hasData?: boolean;
  suggestions?: string[];
  onSendMessage?: (message: string) => void;
}

export function ActionChips({
  hasMap,
  hasChart,
  hasData,
  suggestions = [],
  onSendMessage,
}: ActionChipsProps) {
  const setActiveTab = useAppStore((s) => s.setActiveRightTab);
  const setInputDraft = useChatStore((s) => s.setInputDraft);

  const visibleArtifacts = ARTIFACT_CHIPS.filter((chip) => {
    if (chip.tab === "map") return hasMap;
    if (chip.tab === "charts") return hasChart;
    if (chip.tab === "data") return hasData;
    return false;
  });

  const handleSuggestion = useCallback(
    (text: string) => {
      if (onSendMessage) {
        onSendMessage(text);
      } else {
        setInputDraft(text);
      }
    },
    [onSendMessage, setInputDraft],
  );

  if (visibleArtifacts.length === 0 && suggestions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-3">
      {/* Artifact chips */}
      {visibleArtifacts.map((chip) => {
        const Icon = chip.icon;
        return (
          <button
            key={chip.label}
            onClick={() => setActiveTab(chip.tab)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm",
              "bg-background text-secondary-foreground",
              "hover:border-primary hover:bg-accent-subtle hover:text-primary",
              "transition-colors"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {chip.label}
          </button>
        );
      })}

      {/* Follow-up suggestion chips */}
      {suggestions.slice(0, 3).map((text) => (
        <button
          key={text}
          onClick={() => handleSuggestion(text)}
          className={cn(
            "flex items-center gap-1.5 rounded-md border border-dashed px-3 py-1.5 text-sm",
            "border-primary/40 bg-accent-subtle text-primary",
            "hover:border-primary hover:bg-accent-subtle hover:text-primary",
            "transition-colors"
          )}
        >
          <SuggestionIcon text={text} />
          {text}
        </button>
      ))}
    </div>
  );
}

function SuggestionIcon({ text }: { text: string }) {
  const lower = text.toLowerCase();
  if (lower.includes("optimize") || lower.includes("route")) return <TrendingUp className="h-3.5 w-3.5" />;
  if (lower.includes("compare")) return <BarChart2 className="h-3.5 w-3.5" />;
  if (lower.includes("report")) return <FileText className="h-3.5 w-3.5" />;
  if (lower.includes("trend")) return <TrendingUp className="h-3.5 w-3.5" />;
  return <BarChart3 className="h-3.5 w-3.5" />;
}
