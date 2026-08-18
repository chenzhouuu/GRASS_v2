import { apiUrl } from "@/lib/backend";
import type {
  DashboardCardExecuteRequest,
  DashboardCardResult,
  DashboardCatalog,
  DashboardContext,
  DatabaseSchemaOverview,
} from "@/lib/types";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(message || `Dashboard request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchDashboardContext(): Promise<DashboardContext> {
  const response = await fetch(apiUrl("/api/dashboards/context"), { cache: "no-store" });
  return parseResponse<DashboardContext>(response);
}

export async function fetchDashboardCatalog(): Promise<DashboardCatalog> {
  const response = await fetch(apiUrl("/api/dashboards/catalog"), { cache: "no-store" });
  return parseResponse<DashboardCatalog>(response);
}

export async function executeDashboardCard(
  body: DashboardCardExecuteRequest,
): Promise<DashboardCardResult> {
  const response = await fetch(apiUrl("/api/dashboards/cards/execute"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return parseResponse<DashboardCardResult>(response);
}

export async function fetchDashboardSchema(): Promise<DatabaseSchemaOverview> {
  const response = await fetch(apiUrl("/api/dashboards/schema"), { cache: "no-store" });
  return parseResponse<DatabaseSchemaOverview>(response);
}
