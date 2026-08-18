"use client";

import { useMemo, useState } from "react";
import type { ComponentType } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  AlertTriangle,
  BarChart3,
  Database,
  GitBranch,
  KeyRound,
  Loader2,
  Network,
  Settings,
  Table2,
  Tags,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  DatabaseOverview,
  DatabaseOverviewLabel,
  DatabaseOverviewPattern,
  DatabaseOverviewRelationshipType,
  NvlGraphResult,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const NvlGraphCanvas = dynamic(
  () => import("@/components/database/NvlGraphCanvas").then((mod) => mod.NvlGraphCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading graph...
      </div>
    ),
  },
);

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function KpiCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string;
  value: number;
  description: string;
  icon: ComponentType<{ className?: string }>;
}) {
  return (
    <article className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight">{formatNumber(value)}</p>
        </div>
        <div className="rounded-xl bg-primary/10 p-2 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{description}</p>
    </article>
  );
}

function BarListCard({
  title,
  description,
  items,
  getName,
}: {
  title: string;
  description: string;
  items: Array<{ count: number }>;
  getName: (item: { count: number }) => string;
}) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <article className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>
        <BarChart3 className="h-5 w-5 text-primary" />
      </div>
      <div className="space-y-3">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No data detected.</p>
        ) : items.slice(0, 10).map((item) => {
          const name = getName(item);
          return (
            <div key={name}>
              <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                <span className="truncate font-medium">{name}</span>
                <span className="text-muted-foreground">{formatNumber(item.count)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.max(4, (item.count / max) * 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function GraphCard({
  title,
  description,
  graph,
}: {
  title: string;
  description: string;
  graph: NvlGraphResult;
}) {
  const [error, setError] = useState<string | null>(null);
  const hasGraph = graph.nodes.length > 0;

  return (
    <article className="flex min-h-[420px] flex-col rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>
        <Badge variant="outline">
          {graph.stats?.nodeCount ?? graph.nodes.length} nodes · {graph.stats?.relationshipCount ?? graph.relationships.length} rels
        </Badge>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-xl border bg-muted/20">
        {hasGraph ? (
          <NvlGraphCanvas
            graph={graph}
            onSelect={() => undefined}
            onError={(value) => setError(value instanceof Error ? value.message : "Graph rendering failed")}
          />
        ) : (
          <div className="flex h-full min-h-[300px] items-center justify-center text-sm text-muted-foreground">
            No graph data available for this database yet.
          </div>
        )}
      </div>
      {error && (
        <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          {error}
        </p>
      )}
    </article>
  );
}

function PatternTable({ patterns }: { patterns: DatabaseOverviewPattern[] }) {
  return (
    <article className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="font-semibold">Top Relationship Patterns</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Label-to-label connections discovered from the current database.
            {patterns[0]?.sampled ? " Counts are estimated from a bounded sample." : ""}
          </p>
        </div>
        <Table2 className="h-5 w-5 text-primary" />
      </div>
      <div className="overflow-hidden rounded-xl border">
        <div className="grid grid-cols-[1fr_1fr_1fr_90px] bg-muted/60 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>Start</span>
          <span>Relationship</span>
          <span>End</span>
          <span className="text-right">Count</span>
        </div>
        {patterns.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">No relationship patterns found.</div>
        ) : patterns.slice(0, 12).map((pattern, index) => (
          <div key={`${pattern.relationshipType}-${index}`} className="grid grid-cols-[1fr_1fr_1fr_90px] border-t px-3 py-2 text-xs">
            <span className="truncate">{pattern.startLabels.join(":") || "Unknown"}</span>
            <span className="truncate font-medium text-primary">{pattern.relationshipType}</span>
            <span className="truncate">{pattern.endLabels.join(":") || "Unknown"}</span>
            <span className="text-right text-muted-foreground">{formatNumber(pattern.count)}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function PropertyCoverage({
  labels,
  relationships,
}: {
  labels: DatabaseOverviewLabel[];
  relationships: DatabaseOverviewRelationshipType[];
}) {
  const rows = useMemo(() => {
    const nodeRows = labels.flatMap((label) =>
      label.properties.map((property) => ({
        owner: label.label,
        kind: "Node",
        property,
      })),
    );
    const relRows = relationships.flatMap((relationship) =>
      relationship.properties.map((property) => ({
        owner: relationship.type,
        kind: "Rel",
        property,
      })),
    );
    return [...nodeRows, ...relRows].slice(0, 16);
  }, [labels, relationships]);

  return (
    <article className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="font-semibold">Property Overview</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Properties and value types discovered through Neo4j schema procedures.
          </p>
        </div>
        <KeyRound className="h-5 w-5 text-primary" />
      </div>
      <div className="overflow-hidden rounded-xl border">
        <div className="grid grid-cols-[80px_1fr_1fr_90px] bg-muted/60 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>Kind</span>
          <span>Owner</span>
          <span>Property</span>
          <span>Required</span>
        </div>
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">No properties reported.</div>
        ) : rows.map((row, index) => (
          <div key={`${row.kind}-${row.owner}-${row.property.name}-${index}`} className="grid grid-cols-[80px_1fr_1fr_90px] border-t px-3 py-2 text-xs">
            <span>{row.kind}</span>
            <span className="truncate font-medium">{row.owner}</span>
            <span className="truncate">{row.property.name} <span className="text-muted-foreground">({row.property.types.join(", ") || "unknown"})</span></span>
            <span>{row.property.mandatory ? "Yes" : "No"}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function ConnectionBanner({ overview }: { overview: DatabaseOverview }) {
  return (
    <div className="mb-5 rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="gap-1">
              {overview.connection.connected ? (
                <Wifi className="h-3 w-3 text-emerald-500" />
              ) : (
                <WifiOff className="h-3 w-3 text-amber-500" />
              )}
              {overview.connection.connected ? "Neo4j connected" : "Neo4j disconnected"}
            </Badge>
            <Badge variant="secondary">Database: {overview.connection.database || "unknown"}</Badge>
            <Badge variant="outline">Introspection: {overview.source.toUpperCase()}</Badge>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {overview.connection.uri || "No URI configured"} · source: {overview.connection.source || "unknown"}
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/">
            <Settings className="h-4 w-4" />
            Configure Database
          </Link>
        </Button>
      </div>
    </div>
  );
}

interface DatabaseOverviewDashboardProps {
  schemaOverride: DatabaseOverview;
  embedded?: boolean;
}

export function DatabaseOverviewDashboard({
  schemaOverride,
  embedded = false,
}: DatabaseOverviewDashboardProps) {
  const overview = schemaOverride;

  return (
    <div className="space-y-5">
      {!embedded ? <ConnectionBanner overview={overview} /> : null}

      {overview.warnings.length > 0 && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300">
          {overview.warnings.map((warning) => (
            <div key={warning} className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard title="Nodes" value={overview.stats.nodeCount} description="Total nodes in the active database." icon={Database} />
        <KpiCard title="Relationships" value={overview.stats.relationshipCount} description="Total relationships in the active database." icon={GitBranch} />
        <KpiCard title="Labels" value={overview.stats.labelCount} description="Distinct node labels detected." icon={Tags} />
        <KpiCard title="Relationship Types" value={overview.stats.relationshipTypeCount} description="Distinct relationship types detected." icon={Network} />
        <KpiCard title="Property Keys" value={overview.stats.propertyKeyCount} description="Distinct property keys reported by Neo4j." icon={KeyRound} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <BarListCard
          title="Nodes by Label"
          description="Counts come from APOC statistics when available, otherwise fallback Cypher."
          items={overview.labels}
          getName={(item) => (item as DatabaseOverviewLabel).label}
        />
        <BarListCard
          title="Relationships by Type"
          description="Relationship distribution from the connected database."
          items={overview.relationships}
          getName={(item) => (item as DatabaseOverviewRelationshipType).type}
        />
      </div>

      <GraphCard
        title="Schema Graph"
        description="A label-level graph generated from observed relationship patterns."
        graph={overview.schemaGraph}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <PatternTable patterns={overview.patterns} />
        <PropertyCoverage labels={overview.labels} relationships={overview.relationships} />
      </div>

      <GraphCard
        title="Sample Data Graph"
        description="A bounded sample of actual nodes and relationships from this database."
        graph={overview.sampleGraph}
      />

      {!embedded ? (
        <section className="rounded-2xl border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Database className="h-5 w-5 text-primary" />
            <h2 className="font-semibold">Generated Dashboard Cards</h2>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {overview.generatedCards.map((card) => (
              <div key={card.id} className={cn("rounded-xl border bg-muted/20 p-3", card.cypher && "border-primary/30")}>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">{card.title}</h3>
                  <Badge variant="outline" className="text-2xs">{card.type}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{card.description}</p>
                {card.cypher && (
                  <code className="mt-2 block rounded-md bg-background p-2 text-[11px] text-muted-foreground">
                    {card.cypher}
                  </code>
                )}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

