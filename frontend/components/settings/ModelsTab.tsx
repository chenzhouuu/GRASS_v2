"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAppStore } from "@/stores/appStore";
import {
  useSettingsStore,
  MODEL_CAPABLE_AGENTS,
} from "@/stores/settingsStore";
import type { AgentName } from "@/lib/types";
import type { LLMProvider } from "@/lib/model-config";
import { toast } from "sonner";
import {
  CheckCircle2,
  Loader2,
  RotateCcw,
  AlertCircle,
  Workflow,
  Search as SearchIcon,
  BarChart3,
  TrendingUp,
  FileText,
} from "lucide-react";

// ─── Constants ───────────────────────────────────────────────────────────────

const PROVIDERS: { value: LLMProvider; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "groq", label: "Groq" },
];

const MODELS_BY_PROVIDER: Record<LLMProvider, string[]> = {
  openai: ["gpt-5.4-mini", "gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
  anthropic: ["claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001", "claude-opus-4-6"],
  google: ["gemini-2.0-flash", "gemini-2.0-pro"],
  ollama: ["llama3.1:70b", "llama3.1:8b", "mistral", "codellama"],
  groq: ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
};

const AGENT_META: Record<AgentName, { icon: React.ElementType; desc: string }> = {
  Supervisor: { icon: Workflow, desc: "Orchestrates all agents" },
  Cypher: { icon: SearchIcon, desc: "Neo4j query generation" },
  Analytics: { icon: BarChart3, desc: "Data analysis + charts" },
  Optimization: { icon: TrendingUp, desc: "Supply chain optimization" },
  Report: { icon: FileText, desc: "PDF report generation" },
  ScenarioRunner: { icon: TrendingUp, desc: "What-if scenario re-solve" },
};

// ─── Agent model card ────────────────────────────────────────────────────────

function AgentModelCard({ agent }: { agent: AgentName }) {
  const config = useSettingsStore(
    (s) => s.agentModels[agent] ?? { provider: "openai", model: "gpt-4o" },
  );
  const setAgentModel = useSettingsStore((s) => s.setAgentModel);
  const meta = AGENT_META[agent];
  const Icon = meta.icon;

  const models: string[] =
    MODELS_BY_PROVIDER[config.provider as LLMProvider] ?? [];

  return (
    <div className="rounded-xl border p-4 space-y-3">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium">{agent}</p>
          <p className="text-2xs text-muted-foreground">{meta.desc}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-2xs font-medium text-muted-foreground">
            Provider
          </label>
          <Select
            value={config.provider}
            onValueChange={(v) =>
              setAgentModel(agent, {
                provider: v as LLMProvider,
                model: MODELS_BY_PROVIDER[v as LLMProvider]?.[0] ?? "",
              })
            }
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-2xs font-medium text-muted-foreground">
            Model
          </label>
          <Select
            value={config.model}
            onValueChange={(v) =>
              setAgentModel(agent, {
                provider: config.provider as LLMProvider,
                model: v,
              })
            }
          >
            <SelectTrigger className="h-8 text-sm">
              <SelectValue placeholder="Select model" />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export function ModelsTab() {
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const modelConfigDirty = useSettingsStore((s) => s.modelConfigDirty);
  const saveSessionModelConfig = useSettingsStore((s) => s.saveSessionModelConfig);
  const resetSessionModelConfig = useSettingsStore((s) => s.resetSessionModelConfig);
  const [saving, setSaving] = useState(false);

  const handleApply = useCallback(async () => {
    if (!currentSessionId) {
      toast.info("No active session — settings saved locally");
      return;
    }
    setSaving(true);
    try {
      await saveSessionModelConfig(currentSessionId);
      toast.success("Model config synced to session");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to sync config",
      );
    } finally {
      setSaving(false);
    }
  }, [currentSessionId, saveSessionModelConfig]);

  const handleReset = useCallback(() => {
    resetSessionModelConfig();
    toast.info("Model config reset to defaults");
  }, [resetSessionModelConfig]);

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[14px] font-semibold">Agent models</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Configure the LLM provider and model for each agent.
          {currentSessionId
            ? " Changes sync to the active session."
            : " No session active — changes are saved locally."}
        </p>
      </div>

      <div className="space-y-2.5">
        {MODEL_CAPABLE_AGENTS.map((agent) => (
          <AgentModelCard key={agent} agent={agent} />
        ))}
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={handleApply}
          disabled={saving || !modelConfigDirty}
        >
          {saving ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
          )}
          {saving ? "Syncing..." : "Apply to Session"}
        </Button>
        <Button size="sm" variant="outline" onClick={handleReset}>
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
          Reset
        </Button>
        {modelConfigDirty && (
          <span className="flex items-center gap-1 text-2xs text-warning">
            <AlertCircle className="h-3 w-3" />
            Unsaved
          </span>
        )}
      </div>
    </div>
  );
}
