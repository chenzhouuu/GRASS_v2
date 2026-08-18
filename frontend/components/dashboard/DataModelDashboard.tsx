"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { DatabaseOverviewDashboard } from "@/components/dashboard/DatabaseOverviewDashboard";
import { Button } from "@/components/ui/button";
import { fetchDashboardSchema } from "@/lib/dashboardApi";
import type { DatabaseSchemaOverview } from "@/lib/types";

export function DataModelDashboard() {
  const [schema, setSchema] = useState<DatabaseSchemaOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSchema = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSchema(await fetchDashboardSchema());
    } catch (value) {
      setError(value instanceof Error ? value.message : "Failed to load data model");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSchema();
  }, [loadSchema]);

  if (loading && !schema) {
    return (
      <div className="flex min-h-[520px] items-center justify-center rounded-2xl border bg-card text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading data model...
      </div>
    );
  }

  if (error && !schema) {
    return (
      <div className="flex min-h-[520px] flex-col items-center justify-center rounded-2xl border border-dashed bg-card p-8 text-center">
        <AlertTriangle className="mb-3 h-9 w-9 text-amber-500" />
        <h2 className="text-lg font-semibold">Data model unavailable</h2>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" size="sm" onClick={() => void loadSchema()}>
          <RefreshCw className="h-4 w-4" />
          Try Again
        </Button>
      </div>
    );
  }

  if (!schema) return null;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => void loadSchema()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </div>
      <DatabaseOverviewDashboard schemaOverride={schema} />
    </div>
  );
}
