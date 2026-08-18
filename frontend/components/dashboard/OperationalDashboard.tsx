"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Settings,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BarCardLive } from "@/components/dashboard/cards/BarCardLive";
import { KpiCardLive } from "@/components/dashboard/cards/KpiCardLive";
import { MapCardLive } from "@/components/dashboard/cards/MapCardLive";
import { NetworkCardLive } from "@/components/dashboard/cards/NetworkCardLive";
import { QualityCardLive } from "@/components/dashboard/cards/QualityCardLive";
import { SankeyCardLive } from "@/components/dashboard/cards/SankeyCardLive";
import { TableCardLive } from "@/components/dashboard/cards/TableCardLive";
import { useAppStore } from "@/stores/appStore";
import { useDashboardStore } from "@/stores/dashboardStore";
import { useSettingsStore } from "@/stores/settingsStore";
import type { DashboardCardDefinition } from "@/lib/types";

function formatTime(epoch: number | null): string {
  if (!epoch) return "Never";
  return new Date(epoch).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderCard(card: DashboardCardDefinition) {
  let content;
  switch (card.type) {
    case "bar":
      content = <BarCardLive card={card} />;
      break;
    case "table":
      content = <TableCardLive card={card} />;
      break;
    case "map":
      content = <MapCardLive card={card} />;
      break;
    case "network":
      content = <NetworkCardLive card={card} />;
      break;
    case "sankey":
      content = <SankeyCardLive card={card} />;
      break;
    case "quality":
      content = <QualityCardLive card={card} />;
      break;
    case "kpi":
    default:
      content = <KpiCardLive card={card} />;
      break;
  }

  const size = card.size ?? "small";
  const spanClass =
    size === "wide"
      ? "sm:col-span-2 xl:col-span-4"
      : size === "large"
        ? "sm:col-span-2 xl:col-span-2"
        : size === "medium"
          ? "sm:col-span-2 xl:col-span-2"
          : "";

  return (
    <div key={card.id} className={spanClass}>
      {content}
    </div>
  );
}

export function OperationalDashboard() {
  const context = useDashboardStore((s) => s.context);
  const catalog = useDashboardStore((s) => s.catalog);
  const loadingContext = useDashboardStore((s) => s.loadingContext);
  const loadingCatalog = useDashboardStore((s) => s.loadingCatalog);
  const error = useDashboardStore((s) => s.error);
  const lastLoadedAt = useDashboardStore((s) => s.lastLoadedAt);
  const loadDashboard = useDashboardStore((s) => s.loadDashboard);
  const refreshDashboard = useDashboardStore((s) => s.refreshDashboard);

  const neo4jConnected = useAppStore((s) => s.neo4jConnected);
  const database = useSettingsStore((s) => s.database);

  const connectionKeyRef = useRef<string | null>(null);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    const key = `${database.uri}|${database.database}|${neo4jConnected}`;
    if (connectionKeyRef.current && connectionKeyRef.current !== key) {
      void refreshDashboard();
    }
    connectionKeyRef.current = key;
  }, [neo4jConnected, database.uri, database.database, refreshDashboard]);

  const loading = (loadingContext || loadingCatalog) && !catalog;
  const operationalCards =
    catalog?.cards.filter((card) => card.layer === "operational") ?? [];

  if (loading && !context) {
    return (
      <div className="flex min-h-[520px] items-center justify-center rounded-2xl border bg-card text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading supply chain dashboard...
      </div>
    );
  }

  if (error && !context) {
    return (
      <div className="flex min-h-[520px] flex-col items-center justify-center rounded-2xl border border-dashed bg-card p-8 text-center">
        <AlertTriangle className="mb-3 h-9 w-9 text-amber-500" />
        <h2 className="text-lg font-semibold">Dashboard unavailable</h2>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" size="sm" onClick={() => void refreshDashboard()}>
          <RefreshCw className="h-4 w-4" />
          Try Again
        </Button>
      </div>
    );
  }

  if (!context) return null;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 rounded-2xl border bg-card p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Supply Chain Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Live operational view from the connected Neo4j supply chain graph.
          </p>
          {catalog ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Profile: {catalog.domainProfile} · labels: {catalog.detectedLabels.join(", ") || "none"}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Last loaded {formatTime(lastLoadedAt)}</span>
          <Button size="sm" onClick={() => void refreshDashboard()} disabled={loadingContext || loadingCatalog}>
            {loadingContext || loadingCatalog ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      <div className="rounded-2xl border bg-card p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="gap-1">
              {context.connection.connected ? (
                <Wifi className="h-3 w-3 text-emerald-500" />
              ) : (
                <WifiOff className="h-3 w-3 text-amber-500" />
              )}
              {context.connection.connected ? "Neo4j connected" : "Neo4j disconnected"}
            </Badge>
            <Badge variant="secondary">
              Database: {context.connection.database || "unknown"}
            </Badge>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href="/">
              <Settings className="h-4 w-4" />
              Configure Database
            </Link>
          </Button>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {context.connection.uri || "No URI configured"} · fingerprint: {context.fingerprint}
        </p>
      </div>

      {context.warnings.map((warning) => (
        <div
          key={warning}
          className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300"
        >
          <div className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{warning}</span>
          </div>
        </div>
      ))}

      {!context.connection.connected ? (
        <div className="rounded-2xl border border-dashed bg-card p-8 text-center text-sm text-muted-foreground">
          Connect a Neo4j database to generate operational cards for your supply chain graph.
        </div>
      ) : (
        <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {operationalCards.map((card) => renderCard(card))}
        </div>
      )}
    </div>
  );
}
