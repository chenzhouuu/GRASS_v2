"use client";

import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type ColumnDef,
} from "@tanstack/react-table";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useMapStore } from "@/stores/mapStore";
import { useChatStore } from "@/stores/chatStore";
import { useAppStore } from "@/stores/appStore";
import { Button } from "@/components/ui/button";
import {
  MapPin,
  MessageSquare,
  Download,
  Clipboard,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import type { MapMarker } from "@/lib/types";

// ─── Helpers ────────────────────────────────────────────────────────────────

const GEO_LAT_NAMES = new Set(["latitude", "lat"]);
const GEO_LNG_NAMES = new Set(["longitude", "lng", "lon"]);

function hasGeoColumns(columns: string[]): boolean {
  const lower = columns.map((c) => c.toLowerCase());
  return lower.some((c) => GEO_LAT_NAMES.has(c)) && lower.some((c) => GEO_LNG_NAMES.has(c));
}

function findColumn(columns: string[], candidates: Set<string>): string | undefined {
  return columns.find((c) => candidates.has(c.toLowerCase()));
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

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

// ─── Page size options ──────────────────────────────────────────────────────

const PAGE_SIZES = [25, 50, 100] as const;

// ─── Component ──────────────────────────────────────────────────────────────

export function ResultsTable() {
  const results = useDatabaseStore((s) => s.results);
  const addMarkers = useMapStore((s) => s.addMarkers);
  const setActiveRightTab = useAppStore((s) => s.setActiveRightTab);
  const setInputDraft = useChatStore((s) => s.setInputDraft);

  const [sorting, setSorting] = useState<SortingState>([]);
  const [copiedTimeout, setCopiedTimeout] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up clipboard timeout on unmount
  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const columns = useMemo(() => results?.columns ?? [], [results?.columns]);
  const rows = useMemo(() => results?.rows ?? [], [results?.rows]);
  const hasError = !!results?.error;
  const hasData = rows.length > 0 && !hasError;
  const geoEnabled = hasGeoColumns(columns);

  // Build TanStack columns from result column names
  const tableColumns = useMemo<ColumnDef<Record<string, unknown>, unknown>[]>(() => {
    const helper = createColumnHelper<Record<string, unknown>>();
    return columns.map((col) =>
      helper.accessor((row) => row[col], {
        id: col,
        header: col,
        cell: (info) => formatCellValue(info.getValue()),
        enableSorting: true,
        enableResizing: true,
        size: Math.max(100, col.length * 10),
      })
    );
  }, [columns]);

  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    columnResizeMode: "onChange",
    initialState: {
      pagination: { pageSize: 25 },
    },
  });

  // ── Export handlers ─────────────────────────────────────────────────────

  const handleExportCsv = useCallback(() => {
    if (!hasData) return;
    downloadBlob(rowsToCsv(columns, rows), "results.csv", "text/csv");
  }, [columns, rows, hasData]);

  const handleExportJson = useCallback(() => {
    if (!hasData) return;
    downloadBlob(JSON.stringify(rows, null, 2), "results.json", "application/json");
  }, [rows, hasData]);

  const handleCopyClipboard = useCallback(async () => {
    if (!hasData) return;
    try {
      await navigator.clipboard.writeText(rowsToCsv(columns, rows));
      setCopiedTimeout(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedTimeout(false), 1500);
    } catch {
      // Clipboard API may fail in insecure contexts
    }
  }, [columns, rows, hasData]);

  // ── Show on Map ─────────────────────────────────────────────────────────

  const handleShowOnMap = useCallback(() => {
    if (!geoEnabled || !hasData) return;
    const latCol = findColumn(columns, GEO_LAT_NAMES);
    const lngCol = findColumn(columns, GEO_LNG_NAMES);
    if (!latCol || !lngCol) return;
    const nameCol = columns.find((c) =>
      /^(name|label|title|company|farm)$/i.test(c)
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
  }, [geoEnabled, hasData, columns, rows, addMarkers, setActiveRightTab]);

  // ── Analyze in Chat ─────────────────────────────────────────────────────

  const handleAnalyzeInChat = useCallback(() => {
    if (!hasData) return;
    const summary = `Analyze this data (${rows.length} rows, columns: ${columns.join(", ")}). Here's a sample:\n${JSON.stringify(rows.slice(0, 3), null, 2)}`;
    setInputDraft(summary);
  }, [hasData, rows, columns, setInputDraft]);

  // ── No results state ────────────────────────────────────────────────────

  if (!results || hasError) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        {hasError ? "Query returned an error" : "Run a query to see results"}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Query returned 0 rows
      </div>
    );
  }

  // ── Pagination info ─────────────────────────────────────────────────────

  const { pageIndex, pageSize } = table.getState().pagination;
  const totalRows = rows.length;
  const from = pageIndex * pageSize + 1;
  const to = Math.min((pageIndex + 1) * pageSize, totalRows);

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1 border-b bg-muted/30 px-2 py-1.5">
        <Button
          size="sm"
          variant="ghost"
          onClick={handleShowOnMap}
          disabled={!geoEnabled}
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
          className="h-7 gap-1.5 px-2 text-xs"
          title="Send data to chat for analysis"
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Chat
        </Button>

        <div className="mx-1 h-4 w-px bg-border" />

        <Button
          size="sm"
          variant="ghost"
          onClick={handleExportCsv}
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
          className="h-7 gap-1.5 px-2 text-xs"
          title="Copy to clipboard"
        >
          <Clipboard className="h-3.5 w-3.5" />
          {copiedTimeout ? "Copied!" : "Copy"}
        </Button>

        <div className="flex-1" />

        <span className="text-[11px] text-muted-foreground">
          Showing {from}-{to} of {totalRows} result{totalRows !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <div className="min-h-0 flex-1 overflow-auto" style={{ overflow: "auto", scrollbarGutter: "stable" }}>
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="relative cursor-pointer select-none whitespace-nowrap border-b border-r border-border/50 px-2 py-1.5 text-left font-medium text-muted-foreground"
                    style={{ width: header.getSize() }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <div className="flex items-center gap-1">
                      <span className="truncate">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </span>
                      {{
                        asc: <ChevronUp className="h-3 w-3 shrink-0" />,
                        desc: <ChevronDown className="h-3 w-3 shrink-0" />,
                      }[header.column.getIsSorted() as string] ?? (
                        <ChevronsUpDown className="h-3 w-3 shrink-0 opacity-30" />
                      )}
                    </div>
                    {/* Column resize handle */}
                    <div
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      className="absolute right-0 top-0 h-full w-1 cursor-col-resize select-none touch-none hover:bg-primary/40"
                    />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-border/30 hover:bg-muted/30"
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className="whitespace-nowrap border-r border-border/20 px-2 py-1"
                    style={{ width: cell.column.getSize() }}
                  >
                    <span className="block truncate">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalRows > 25 && (
        <div className="flex items-center justify-between border-t bg-muted/30 px-2 py-1">
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted-foreground">Rows:</span>
            <select
              className="h-6 rounded border border-border bg-background px-1 text-[11px]"
              value={pageSize}
              onChange={(e) => table.setPageSize(Number(e.target.value))}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="h-6 w-6 p-0"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="text-[11px] text-muted-foreground">
              Page {pageIndex + 1} of {table.getPageCount()}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="h-6 w-6 p-0"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
