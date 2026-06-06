import { apiUrl } from "@/lib/backend";
import type { DatabaseConfig } from "@/stores/settingsStore";

export interface Neo4jRuntimeConfig extends DatabaseConfig {
  connected: boolean;
  source: string;
}

export async function fetchNeo4jConfig(): Promise<Neo4jRuntimeConfig> {
  const res = await fetch(apiUrl("/api/neo4j/config"));
  if (!res.ok) {
    throw new Error(`Failed to fetch Neo4j config (${res.status})`);
  }
  return (await res.json()) as Neo4jRuntimeConfig;
}

export async function updateNeo4jConfig(
  config: DatabaseConfig,
): Promise<Neo4jRuntimeConfig> {
  const res = await fetch(apiUrl("/api/neo4j/config"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Connection failed" }));
    throw new Error(body.detail ?? "Connection failed");
  }
  return (await res.json()) as Neo4jRuntimeConfig;
}
