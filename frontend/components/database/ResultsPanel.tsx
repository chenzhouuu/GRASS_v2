"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Clipboard,
  Database,
  Download,
  GitBranch,
  MapPin,
  MessageSquare,
  Table2,
  Code2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { useChatStore } from "@/stores/chatStore";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useMapStore } from "@/stores/mapStore";
import type { DatabaseResultsViewMode, MapMarker } from "@/lib/types";
import { GraphResultsView } from "./GraphResultsView";
import { RawResultsView } from "./RawResultsView";
import { ResultsTable, formatCellValue } from "./ResultsTable";

const GEO_LAT_NAMES = new Set(["latitude", "lat"]);
const GEO_LNG_NAMES = new Set(["longitude", "lng", "lon"]);

function rowsToCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const escape = (v: string) => {
    if (v.includes(",") || v.includes('"') || v.includes("\n")) {
      return `"${v.replace(/"/g, '""')}"`;
    }
    return v;
  };
  const header = columns.map(escape).join(",");
  const body = rows
    .map((row) => columns.map((col) => escape(formatCellValue(row[col]))).join(","))
    .join("\n");
  return `${header}\n${body}`;
}

function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function hasGeoColumns(columns: string[]): boolean {
  const lower = columns.map((c) => c.toLowerCase());
  return lower.some((c) => GEO_LAT_NAMES.has(c)) && lower.some((c) => GEO_LNG_NAMES.has(c));
}

function findColumn(columns: string[], candidates: Set<string>): string | undefined {
  return columns.find((c) => candidates.has(c.toLowerCase()));
}

function ViewButton({
  mode,
  current,
  disabled,
  children,
  onClick,
}: {
  mode: DatabaseResultsViewMode;
  current: DatabaseResultsViewMode;
  disabled?: boolean;
  children: React.ReactNode;
  onClick: (mode: DatabaseResultsViewMode) => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onClick(mode)}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        current === mode
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function ResultsPanel() {
  const results = useDatabaseStore((s) => s.results);
  const viewMode = useDatabaseStore((s) => s.resultsViewMode);
  const setViewMode = useDatabaseStore((s) => s.setResultsViewMode);
  const addMarkers = useMapStore((s) => s.addMarkers);
  const setActiveRightTab = useAppStore((s) => s.setActiveRightTab);
  const setInputDraft = useChatStore((s) => s.setInputDraft);
  const [copiedTimeout, setCopiedTimeout] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rows = useMemo(() => results?.rows ?? [], [results?.rows]);
  const columns = useMemo(() => results?.columns ?? [], [results?.columns]);
  const graph = results?.graph;
  const hasGraph =
    !!graph && (graph.nodes.length > 0 || graph.relationships.length > 0);
  const hasData = rows.length > 0 && !results?.error;
  const geoEnabled = hasGeoColumns(columns);

  const stats = useMemo(() => {
    const nodeCount = graph?.stats?.nodeCount ?? graph?.nodes.length ?? 0;
    const relCount =
      graph?.stats?.relationshipCount ?? graph?.relationships.length ?? 0;
    return { nodeCount, relCount };
  }, [graph]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const handleExportCsv = useCallback(() => {
    if (!hasData) return;
    downloadBlob(rowsToCsv(columns, rows), "results.csv", "text/csv");
  }, [columns, hasData, rows]);

  const handleExportJson = useCallback(() => {
    if (!results) return;
    downloadBlob(JSON.stringify(results.rows, null, 2), "results.json", "application/json");
  }, [results]);

  const handleCopyClipboard = useCallback(async () => {
    if (!hasData) return;
    try {
      await navigator.clipboard.writeText(rowsToCsv(columns, rows));
      setCopiedTimeout(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedTimeout(false), 1500);
    } catch {
      setCopiedTimeout(false);
    }
  }, [columns, hasData, rows]);

  const handleShowOnMap = useCallback(() => {
    if (!geoEnabled || !hasData) return;
    const latCol = findColumn(columns, GEO_LAT_NAMES);
    const lngCol = findColumn(columns, GEO_LNG_NAMES);
    if (!latCol || !lngCol) return;
    const nameCol = columns.find((c) =>
      /^(name|label|title|company|farm)$/i.test(c),
    );

    const markers: MapMarker[] = rows
      .filter((r) => {
        const lat = Number(r[latCol]);
        const lng = Number(r[lngCol]);
        return !isNaN(lat) && !isNaN(lng);
      })
      .map((r, i) => ({
        id: `db-${i}-${r[latCol]}-${r[lngCol]}`,
        lat: Number(r[latCol]),
        lng: Number(r[lngCol]),
        label: nameCol ? String(r[nameCol]) : `Row ${i + 1}`,
        properties: r,
      }));

    addMarkers(markers);
    setActiveRightTab("map");
  }, [addMarkers, columns, geoEnabled, hasData, rows, setActiveRightTab]);

  const handleAnalyzeInChat = useCallback(() => {
    if (!hasData) return;
    const summary = `Analyze this data (${rows.length} rows, columns: ${columns.join(", ")}). Here's a sample:\n${JSON.stringify(rows.slice(0, 3), null, 2)}`;
    setInputDraft(summary);
  }, [columns, hasData, rows, setInputDraft]);

  const safeViewMode = viewMode === "graph" && !hasGraph ? "table" : viewMode;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b bg-muted/30 px-2 py-1.5">
        <div className="flex rounded-md bg-muted p-0.5">
          <ViewButton mode="table" current={safeViewMode} onClick={setViewMode}>
            <Table2 className="h-3.5 w-3.5" />
            Table
          </ViewButton>
          <ViewButton
            mode="graph"
            current={safeViewMode}
            disabled={!hasGraph}
            onClick={setViewMode}
          >
            <GitBranch className="h-3.5 w-3.5" />
            Graph
          </ViewButton>
          <ViewButton mode="raw" current={safeViewMode} onClick={setViewMode}>
            <Code2 className="h-3.5 w-3.5" />
            Raw
          </ViewButton>
        </div>

        <div className="mx-1 h-4 w-px bg-border" />

        <Button
          size="sm"
          variant="ghost"
          onClick={handleShowOnMap}
          disabled={!geoEnabled || !hasData}
          className="h-7 gap-1.5 px-2 text-xs"
          title={geoEnabled ? "Show results on map" : "No lat/lng columns"}
        >
          <MapPin className="h-3.5 w-3.5" />
          Map
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleAnalyzeInChat}
          disabled={!hasData}
          className="h-7 gap-1.5 px-2 text-xs"
          title="Send data to chat for analysis"
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Chat
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleExportCsv}
          disabled={!hasData}
          className="h-7 gap-1.5 px-2 text-xs"
          title="Export as CSV"
        >
          <Download className="h-3.5 w-3.5" />
          CSV
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleExportJson}
          disabled={!results}
          className="h-7 gap-1.5 px-2 text-xs"
          title="Export as JSON"
        >
          <Download className="h-3.5 w-3.5" />
          JSON
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleCopyClipboard}
          disabled={!hasData}
          className="h-7 gap-1.5 px-2 text-xs"
          title="Copy CSV to clipboard"
        >
          <Clipboard className="h-3.5 w-3.5" />
          {copiedTimeout ? "Copied" : "Copy"}
        </Button>

        <div className="flex-1" />

        <div className="flex flex-wrap items-center gap-1">
          <Badge variant="outline" className="gap-1 px-1.5 py-0 text-[10px]">
            <Database className="h-3 w-3" />
            {rows.length} rows
          </Badge>
          {stats.nodeCount > 0 && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {stats.nodeCount} nodes
            </Badge>
          )}
          {stats.relCount > 0 && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {stats.relCount} rels
            </Badge>
          )}
          {results?.executionTimeMs !== undefined && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {results.executionTimeMs}ms
            </Badge>
          )}
          {(results?.truncated || results?.graphTruncated || graph?.stats?.truncated) && (
            <Badge variant="outline" className="border-warning/40 px-1.5 py-0 text-[10px] text-warning">
              truncated
            </Badge>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {safeViewMode === "graph" && <GraphResultsView graph={graph} />}
        {safeViewMode === "raw" && results && <RawResultsView results={results} />}
        {safeViewMode === "table" && <ResultsTable showToolbar={false} />}
      </div>
    </div>
  );
}
