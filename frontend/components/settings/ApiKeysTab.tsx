"use client";

import { useState, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSettingsStore } from "@/stores/settingsStore";
import { useAppStore } from "@/stores/appStore";
import type { RuntimeApiKeyProvider } from "@/lib/model-config";
import { isValidProviderKey } from "@/lib/validators";
import { Eye, EyeOff, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

function PasswordInput({
  id,
  value,
  onChange,
  placeholder,
  error,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  error?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn("pr-9 h-8 text-sm", error && "border-destructive")}
      />
      <button
        type="button"
        onClick={() => setVisible(!visible)}
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground transition-colors"
        aria-label={visible ? "Hide" : "Show"}
      >
        {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

const PROVIDERS: {
  key: RuntimeApiKeyProvider;
  label: string;
  placeholder: string;
  hint: string;
}[] = [
  { key: "openai", label: "OpenAI", placeholder: "sk-...", hint: "Used by GPT-4o, GPT-4o-mini" },
  { key: "anthropic", label: "Anthropic", placeholder: "sk-ant-...", hint: "Used by Claude models" },
  { key: "google", label: "Google Gemini", placeholder: "AIza...", hint: "Used by Gemini models" },
];

export function ApiKeysTab() {
  const providerApiKeys = useSettingsStore((s) => s.providerApiKeys);
  const setProviderApiKey = useSettingsStore((s) => s.setProviderApiKey);
  const modelConfigDirty = useSettingsStore((s) => s.modelConfigDirty);
  const saveSessionModelConfig = useSettingsStore((s) => s.saveSessionModelConfig);
  const currentSessionId = useAppStore((s) => s.currentSessionId);
  const [saving, setSaving] = useState(false);

  const handleApply = useCallback(async () => {
    if (!currentSessionId) {
      toast.info("No active session — keys saved locally");
      return;
    }
    setSaving(true);
    try {
      await saveSessionModelConfig(currentSessionId);
      toast.success("API keys synced to session");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to sync keys",
      );
    } finally {
      setSaving(false);
    }
  }, [currentSessionId, saveSessionModelConfig]);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[14px] font-semibold">API keys</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Runtime keys override backend environment variables for this session.
          Stored in your browser only — never sent to third parties.
        </p>
      </div>

      <div className="space-y-4">
        {PROVIDERS.map(({ key, label, placeholder, hint }) => {
          const value = providerApiKeys[key];
          const hasKey = value.length > 0;
          const valid = !hasKey || isValidProviderKey(key, value);

          return (
            <div key={key} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor={`${key}-key`} className="block text-sm font-medium">
                  {label}
                </label>
                {hasKey && (
                  valid ? (
                    <span className="flex items-center gap-1 text-2xs text-success">
                      <CheckCircle2 className="h-3 w-3" />
                      Valid format
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-2xs text-destructive">
                      <AlertCircle className="h-3 w-3" />
                      Invalid format
                    </span>
                  )
                )}
              </div>
              <PasswordInput
                id={`${key}-key`}
                value={value}
                onChange={(v) => setProviderApiKey(key, v)}
                placeholder={placeholder}
                error={hasKey && !valid}
              />
              <p className="text-2xs text-muted-foreground">{hint}</p>
            </div>
          );
        })}
      </div>

      {/* Apply button */}
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
    </div>
  );
}
