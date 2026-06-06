"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Download,
  ExternalLink,
  RotateCcw,
  RotateCw,
  FileText,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAppStore } from "@/stores/appStore";
import { useChatStore } from "@/stores/chatStore";
import { sendChatMessage } from "@/lib/api";

export function ReportViewer() {
  const reportUrl = useAppStore((s) => s.reportUrl);
  const reportTitle = useAppStore((s) => s.reportTitle);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);

  // Reset state when report URL changes
  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    setReloadKey((k) => k + 1);
  }, [reportUrl]);

  const handleDownload = useCallback(() => {
    if (!reportUrl) return;
    const a = document.createElement("a");
    a.href = reportUrl;
    a.download = reportTitle ?? "report.pdf";
    a.click();
  }, [reportUrl, reportTitle]);

  const handleOpenNewTab = useCallback(() => {
    if (!reportUrl) return;
    window.open(reportUrl, "_blank", "noopener,noreferrer");
  }, [reportUrl]);

  const handleReload = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    setReloadKey((k) => k + 1);
  }, []);

  const handleRegenerate = useCallback(() => {
    if (isStreaming) return;
    sendChatMessage(
      "Please regenerate the report with any improvements you see fit.",
    );
  }, [isStreaming]);

  // ── Empty state ──────────────────────────────────────────────────────────
  if (!reportUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <FileText className="h-10 w-10 opacity-20" />
        <div className="text-center">
          <p className="text-sm font-medium">No report yet</p>
          <p className="mt-1 text-xs">
            Reports will appear here when generated
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* ── Toolbar ────────────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-1 border-b bg-muted/30 px-2 py-1.5">
        <div className="flex-1 text-xs text-muted-foreground">
          Browser PDF preview
        </div>

        {/* Actions */}
        <Button
          size="sm"
          variant="ghost"
          onClick={handleDownload}
          className="h-7 gap-1 px-2 text-[11px]"
          title="Download PDF"
        >
          <Download className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleOpenNewTab}
          className="h-7 gap-1 px-2 text-[11px]"
          title="Open in new tab"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleReload}
          className="h-7 gap-1 px-2 text-[11px]"
          title="Reload preview"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={handleRegenerate}
          disabled={isStreaming}
          className="h-7 gap-1 px-2 text-[11px]"
          title="Regenerate report"
        >
          <RotateCw className="h-3.5 w-3.5" />
          <span className="hidden @[340px]:inline">Regenerate</span>
        </Button>
      </div>

      {/* ── Title bar ──────────────────────────────────────────────────────── */}
      {reportTitle && (
        <div className="shrink-0 border-b px-3 py-1.5">
          <p className="truncate text-xs font-medium">{reportTitle}</p>
        </div>
      )}

      {/* ── PDF viewer ─────────────────────────────────────────────────────── */}
      <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden bg-muted/20">
        {loadError ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-destructive">
            <FileText className="h-8 w-8 opacity-50" />
            <p className="text-sm">Failed to load PDF</p>
            <p className="text-xs text-muted-foreground">{loadError}</p>
            <Button
              size="sm"
              variant="outline"
              onClick={handleReload}
              className="mt-2 h-7 text-xs"
            >
              <RefreshCw className="mr-1 h-3 w-3" />
              Retry
            </Button>
          </div>
        ) : (
          <div className="relative h-full w-full">
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 bg-background/70 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm">Loading PDF...</span>
              </div>
            )}
            <iframe
              key={reloadKey}
              src={reportUrl}
              title={reportTitle ?? "Generated report"}
              className="h-full w-full border-0"
              onLoad={() => {
                setLoading(false);
                setLoadError(null);
              }}
              onError={() => {
                setLoading(false);
                setLoadError("The browser failed to render this PDF preview.");
              }}
            />
            <div className="pointer-events-none absolute bottom-2 right-2 rounded bg-background/80 px-2 py-1 text-[10px] text-muted-foreground shadow-sm">
              If preview fails, use open/download actions.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
