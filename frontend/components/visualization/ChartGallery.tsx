"use client";

import { useMemo, useCallback } from "react";
import { Download, MessageSquare, BarChart3, Maximize2 } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { InteractiveChart } from "./InteractiveChart";
import { ChartErrorBoundary } from "./ChartErrorBoundary";
import { EmptyState } from "@/components/shared/EmptyState";
import { sendChatMessage } from "@/lib/api";
import type { VisualizationData } from "@/lib/types";
import { apiUrl } from "@/lib/backend";

export function ChartGallery() {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const charts = useMemo(() => {
    const result: { viz: VisualizationData; messageId: string }[] = [];
    for (const msg of messages) {
      if (msg.visualizations) {
        for (const viz of msg.visualizations) {
          if (viz.type === "chart") {
            result.push({ viz, messageId: msg.id });
          }
        }
      }
    }
    return result;
  }, [messages]);

  const handleDiscuss = useCallback(
    (viz: VisualizationData) => {
      if (isStreaming) return;
      const title = viz.title ?? "this chart";
      sendChatMessage(`Tell me more about ${title}. What insights can you draw from it?`);
    },
    [isStreaming]
  );

  const handleDownload = useCallback(async (viz: VisualizationData) => {
    const data = viz.data as Record<string, unknown>;
    const fileId = typeof data.file_id === "string" ? data.file_id : null;
    const rawUrl =
      typeof data.image_url === "string"
        ? data.image_url
        : typeof data.url === "string"
          ? data.url
          : null;

    if (fileId || rawUrl) {
      const href = fileId
        ? apiUrl(`/api/files/${encodeURIComponent(fileId)}`)
        : rawUrl!.startsWith("http://") || rawUrl!.startsWith("https://")
          ? rawUrl!
          : apiUrl(rawUrl!);
      const a = document.createElement("a");
      a.href = href;
      a.download = viz.title ?? "chart";
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.click();
      return;
    }

    try {
      const Plotly = await import("plotly.js-dist-min");
      const container = document.querySelector(
        `[data-chart-id="${viz.id}"] .js-plotly-plot`
      ) as HTMLElement | null;
      if (container) {
        await Plotly.downloadImage(container as unknown as Plotly.PlotlyHTMLElement, {
          format: "png",
          width: 1200,
          height: 800,
          filename: viz.title ?? "chart",
        });
      }
    } catch {
      // Download failed silently
    }
  }, []);

  if (charts.length === 0) {
    return (
      <EmptyState
        icon={<BarChart3 className="h-10 w-10" />}
        title="No charts yet"
        subtitle="Ask an analytical question to generate charts"
      />
    );
  }

  return (
    <div
      className="min-h-0 flex flex-1 flex-col gap-3 overflow-y-auto p-3 scrollbar-thin"
      style={{ scrollbarGutter: "stable" }}
    >
      {charts.map(({ viz }) => (
        <div
          key={viz.id}
          data-chart-id={viz.id}
          className="overflow-hidden rounded-lg border bg-card"
        >
          {viz.title && (
            <div className="border-b px-3.5 py-2">
              <h3 className="text-xs font-medium text-secondary-foreground">{viz.title}</h3>
            </div>
          )}

          <div className="min-h-[280px] h-[45vh] max-h-[500px] overflow-hidden p-3.5">
            <ChartErrorBoundary title={viz.title}>
              <InteractiveChart
                visualization={viz}
                showTitle={false}
                showDownloadButton={false}
              />
            </ChartErrorBoundary>
          </div>

          <div className="flex items-center justify-end gap-1 border-t px-3 py-1.5">
            <button
              onClick={() => handleDownload(viz)}
              className="flex items-center gap-1 rounded px-2 py-1 text-2xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <Download className="h-3 w-3" />
              PNG
            </button>
            <button
              onClick={() => handleDiscuss(viz)}
              disabled={isStreaming}
              className="flex items-center gap-1 rounded px-2 py-1 text-2xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
            >
              <MessageSquare className="h-3 w-3" />
              Discuss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
