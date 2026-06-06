"use client";

import { useMemo, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChartErrorBoundary } from "./ChartErrorBoundary";
import type { VisualizationData } from "@/lib/types";
import { apiUrl } from "@/lib/backend";
import { cn } from "@/lib/utils";

// ── Dynamic import with factory pattern ──────────────────────────────────────
// react-plotly.js needs the factory pattern to work with plotly.js-dist-min
// (the minified distribution). The import is SSR-disabled because Plotly
// requires `window` and DOM APIs.

const Plot = dynamic(
  () =>
    Promise.all([
      import("plotly.js-dist-min"),
      import("react-plotly.js/factory"),
    ]).then(([Plotly, factory]) => {
      // factory.default is the createPlotlyComponent function
      const createPlot = factory.default ?? factory;
      const PlotlyLib = Plotly.default ?? Plotly;
      const PlotComponent = createPlot(PlotlyLib);
      // next/dynamic expects { default: Component }
      return { default: PlotComponent } as { default: React.ComponentType<any> };
    }),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    ),
  }
);

interface InteractiveChartProps {
  visualization: VisualizationData;
  compact?: boolean;
  className?: string;
  showTitle?: boolean;
  showDownloadButton?: boolean;
}

export function InteractiveChart({
  visualization,
  compact = false,
  className,
  showTitle = !compact,
  showDownloadButton = !compact,
}: InteractiveChartProps) {
  const plotRef = useRef<HTMLDivElement>(null);

  const { data, layout, config, imageSrc } = useMemo(() => {
    const spec = visualization.data as {
      data?: Plotly.Data[];
      layout?: Partial<Plotly.Layout>;
      config?: Partial<Plotly.Config>;
      file_id?: string;
      url?: string;
      image_url?: string;
    };

    const fileId = typeof spec.file_id === "string" ? spec.file_id : null;
    const rawUrl =
      typeof spec.image_url === "string"
        ? spec.image_url
        : typeof spec.url === "string"
          ? spec.url
          : null;

    const resolvedImageSrc = fileId
      ? apiUrl(`/api/files/${encodeURIComponent(fileId)}`)
      : rawUrl
        ? rawUrl.startsWith("http://") || rawUrl.startsWith("https://")
          ? rawUrl
          : apiUrl(rawUrl)
        : null;

    // Extract Plotly trace data — handle both {data: [...]} and bare array
    const plotData: Plotly.Data[] = Array.isArray(spec.data)
      ? spec.data
      : Array.isArray(spec as unknown)
        ? (spec as unknown as Plotly.Data[])
        : [];

    const specLayout: Partial<Plotly.Layout> = { ...(spec.layout ?? {}) };
    const preserveHeight = specLayout.height && specLayout.height > 400;
    if (!preserveHeight) {
      delete specLayout.height;
    }
    delete specLayout.width;
    delete specLayout.autosize;

    const isSankey = Array.isArray(spec.data) && spec.data.some(
      (t: Record<string, unknown>) => t.type === "sankey"
    );

    const plotLayout: Partial<Plotly.Layout> = {
      ...specLayout,
      autosize: true,
      margin: isSankey
        ? { l: 10, r: 10, t: 40, b: 10 }
        : compact
          ? { l: 40, r: 16, t: 32, b: 40 }
          : { l: 50, r: 30, t: 40, b: 50 },
      title: !showTitle
        ? undefined
        : visualization.title
          ? { text: visualization.title }
          : specLayout.title,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { size: compact ? 10 : 12 },
    };

    const plotConfig: Partial<Plotly.Config> = {
      responsive: true,
      displayModeBar: !compact,
      displaylogo: false,
      modeBarButtonsToRemove: ["sendDataToCloud", "lasso2d", "select2d"] as Plotly.ModeBarDefaultButtons[],
      ...spec.config,
    };

    return {
      data: plotData,
      layout: plotLayout,
      config: plotConfig,
      imageSrc: resolvedImageSrc,
    };
  }, [visualization, compact, showTitle]);

  const handleDownload = useCallback(async () => {
    if (imageSrc) {
      const a = document.createElement("a");
      a.href = imageSrc;
      a.download = visualization.title ?? "chart";
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.click();
      return;
    }

    try {
      const Plotly = await import("plotly.js-dist-min");
      const container = plotRef.current?.querySelector(".js-plotly-plot") as HTMLElement | null;
      if (container) {
        await (Plotly.default ?? Plotly).downloadImage(container as unknown as Plotly.PlotlyHTMLElement, {
          format: "png",
          width: 1200,
          height: 800,
          filename: visualization.title ?? "chart",
        });
      }
    } catch {
      // Download failed silently
    }
  }, [visualization.title, imageSrc]);

  return (
    <div
      ref={plotRef}
      className={cn("flex h-full min-h-0 w-full flex-col overflow-hidden", className)}
    >
      <div className="min-h-0 flex-1 overflow-hidden">
        <ChartErrorBoundary title={visualization.title}>
          {imageSrc ? (
            <div className="relative h-full w-full bg-muted/20">
              <Image
                src={imageSrc}
                alt={visualization.title ?? "Generated chart"}
                fill
                className="object-contain"
                sizes="(max-width: 1024px) 100vw, 50vw"
                unoptimized
              />
            </div>
          ) : data.length > 0 ? (
            <Plot
              data={data}
              layout={layout}
              config={config}
              useResizeHandler
              style={{ width: "100%", height: "100%" }}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
              No chart data available
            </div>
          )}
        </ChartErrorBoundary>
      </div>
      {showDownloadButton && data.length > 0 && (
        <div className="flex shrink-0 justify-end px-2 pb-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDownload}
            className="h-6 gap-1 px-2 text-[11px]"
          >
            <Download className="h-3 w-3" />
            Download PNG
          </Button>
        </div>
      )}
    </div>
  );
}
