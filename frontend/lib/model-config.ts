import { apiUrl } from "@/lib/backend";
import type { AgentName } from "@/lib/types";

export type LLMProvider = "openai" | "anthropic" | "google" | "ollama" | "groq";
export type RuntimeApiKeyProvider = "openai" | "anthropic" | "google";

export interface ModelConfig {
  provider: LLMProvider;
  model: string;
}

export interface ProviderApiKeys {
  openai: string;
  anthropic: string;
  google: string;
}

export interface SessionModelConfigPayload {
  agent_models: Partial<Record<AgentName, ModelConfig>>;
  api_keys: ProviderApiKeys;
}

export interface SessionModelConfigResponse {
  session_id: string;
  agent_models: Record<AgentName, ModelConfig>;
  api_keys: ProviderApiKeys;
  source: "defaults" | "session";
}

export async function fetchSessionModelConfig(
  sessionId: string,
): Promise<SessionModelConfigResponse> {
  const res = await fetch(apiUrl(`/api/sessions/${sessionId}/model-config`));
  if (!res.ok) {
    throw new Error(`Failed to fetch session model config (${res.status})`);
  }
  return (await res.json()) as SessionModelConfigResponse;
}

export async function updateSessionModelConfig(
  sessionId: string,
  payload: SessionModelConfigPayload,
): Promise<SessionModelConfigResponse> {
  const res = await fetch(apiUrl(`/api/sessions/${sessionId}/model-config`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Failed to save model config" }));
    throw new Error(body.detail ?? "Failed to save model config");
  }
  return (await res.json()) as SessionModelConfigResponse;
}
