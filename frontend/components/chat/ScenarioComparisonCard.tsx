"use client";

import { useState } from "react";
import {
  ChevronDown,
  GitCompareArrows,
  Minus,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import type { KpiDelta, ScenarioComparison, VisualizationData } from "@/lib/types";
import { InteractiveChart } from "@/components/visualization/InteractiveChart";

type DeltaStatus = "good" | "bad" | "flat";

function deltaStatus(delta: number, good: KpiDelta["good_direction"]): DeltaStatus {
  if (Math.abs(delta) < 1e-9 || good === "flat") return "flat";
  const improving = (good === "down" && delta < 0) || (good === "up" && delta > 0);
  return improving ? "good" : "bad";
}

const STATUS_TEXT: Record<DeltaStatus, string> = {
  good: "text-emerald-600 dark:text-emerald-400",
  bad: "text-rose-600 dark:text-rose-400",
  flat: "text-muted-foreground",
};
const STATUS_PILL: Record<DeltaStatus, string> = {
  good: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  bad: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  flat: "bg-muted text-muted-foreground",
};

function fmt(value: number, unit: string): string {
  const abs = Math.abs(value);
  let body: string;
  if (abs >= 1_000_000) body = (value / 1_000_000).toFixed(2) + "M";
  else if (abs >= 1_000) body = (value / 1_000).toFixed(1) + "K";
  else body = Number.isInteger(value) ? value.toString() : value.toFixed(2);
  if (unit === "$") return "$" + body;
  if (unit) return `${body} ${unit}`;
  return body;
}

function prettyName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function DeltaPill({ delta, pct, good }: { delta: number; pct: number | null; good: KpiDelta["good_direction"] }) {
  const status = deltaStatus(delta, good);
  const Icon = Math.abs(delta) < 1e-9 ? Minus : delta > 0 ? TrendingUp : TrendingDown;
  const label = pct === null ? (delta > 0 ? "+" : "") + fmt(delta, "") : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_PILL[status]}`}>
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}

export function ScenarioComparisonCard({ comparison }: { comparison: ScenarioComparison }) {
  const [open, setOpen] = useState(false);
  const c = comparison;

  const objKpi = c.kpi_deltas.find((k) => k.name === "objective_value");
  const objStatus = objKpi ? deltaStatus(objKpi.delta, objKpi.good_direction) : "flat";
  const gridKpis = c.kpi_deltas.filter((k) => k.name !== "objective_value");

  const waterfallViz: VisualizationData | null = c.waterfall
    ? {
        id: `${c.scenario_run_id}-waterfall`,
        type: "chart",
        title: "Objective change",
        data: c.waterfall as unknown as Record<string, unknown>,
      }
    : null;

  return (
    <div className="mt-4 w-full max-w-2xl overflow-hidden rounded-xl border shadow-sm bg-gradient-to-br from-slate-50 to-slate-100/70 dark:from-slate-900 dark:to-slate-800/70 dark:border-slate-700">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b px-4 py-3 dark:border-slate-700">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10 text-primary">
          <GitCompareArrows className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{c.scenario_name || "What-if scenario"}</div>
          {c.scenario_description && (
            <div className="truncate text-xs text-muted-foreground">{c.scenario_description}</div>
          )}
        </div>
        <span className="ml-auto shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
          What-if
        </span>
      </div>

      {/* headline objective */}
      {objKpi && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b px-4 py-3 dark:border-slate-700">
          <span className="text-xs text-muted-foreground">
            Objective — baseline <b className="text-foreground">{fmt(objKpi.baseline, objKpi.unit)}</b>
          </span>
          <span className="text-muted-foreground">→</span>
          <span className={`text-2xl font-semibold tracking-tight ${STATUS_TEXT[objStatus]}`}>
            {fmt(objKpi.scenario, objKpi.unit)}
          </span>
          <DeltaPill delta={objKpi.delta} pct={objKpi.pct} good={objKpi.good_direction} />
        </div>
      )}

      {/* narrative */}
      {c.narrative && (
        <div className="border-b px-4 py-3 text-[13px] leading-relaxed dark:border-slate-700">
          <p className="rounded-md border-l-2 border-primary/50 bg-muted/40 px-3 py-2 text-foreground">
            {c.narrative}
          </p>
        </div>
      )}

      {/* KPI delta grid */}
      {gridKpis.length > 0 && (
        <div className="border-b px-4 py-3 dark:border-slate-700">
          <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Key metrics — baseline → scenario
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {gridKpis.map((k) => (
              <div key={k.name} className="rounded-lg border bg-background p-3">
                <div className="text-[11px] text-muted-foreground">{prettyName(k.name)}</div>
                <div className="mt-1.5 flex items-baseline gap-1.5">
                  <span className="text-xs text-muted-foreground">{fmt(k.baseline, k.unit)} →</span>
                  <span className="text-base font-semibold tracking-tight">{fmt(k.scenario, k.unit)}</span>
                </div>
                <div className="mt-2">
                  <DeltaPill delta={k.delta} pct={k.pct} good={k.good_direction} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* binding-constraint shift */}
      {(c.binding_added.length > 0 || c.binding_removed.length > 0) && (
        <div className="border-b px-4 py-3 dark:border-slate-700">
          <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Binding-constraint shift · where the bottleneck moved
          </div>
          <div className="flex flex-col gap-2 text-xs">
            <div className="flex items-start gap-2">
              <span className="min-w-[110px] pt-0.5 text-muted-foreground">Newly binding</span>
              <div className="flex flex-wrap gap-1.5">
                {c.binding_added.length ? (
                  c.binding_added.map((b) => (
                    <span key={b} className="rounded-md bg-rose-50 px-2 py-0.5 font-medium text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                      ▲ {b}
                    </span>
                  ))
                ) : (
                  <span className="rounded-md bg-muted px-2 py-0.5 text-muted-foreground">none</span>
                )}
              </div>
            </div>
            <div className="flex items-start gap-2">
              <span className="min-w-[110px] pt-0.5 text-muted-foreground">No longer binding</span>
              <div className="flex flex-wrap gap-1.5">
                {c.binding_removed.length ? (
                  c.binding_removed.map((b) => (
                    <span key={b} className="rounded-md bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                      ▼ {b}
                    </span>
                  ))
                ) : (
                  <span className="rounded-md bg-muted px-2 py-0.5 text-muted-foreground">none</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* details toggle: waterfall + full table */}
      {(waterfallViz || c.kpi_deltas.length > 0) && (
        <>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <span>{open ? "Hide details" : "Show details — waterfall & full table"}</span>
            <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>

          {open && (
            <div className="space-y-3 px-4 pb-4">
              {waterfallViz && (
                <div className="overflow-hidden rounded-lg border bg-background">
                  <div className="border-b px-3.5 py-2 text-xs font-medium text-muted-foreground">
                    Objective waterfall (baseline → scenario)
                  </div>
                  <div className="h-[260px]">
                    <InteractiveChart visualization={waterfallViz} compact />
                  </div>
                </div>
              )}

              <div className="overflow-hidden rounded-lg border bg-background">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-muted/60 text-muted-foreground">
                      <th className="px-3 py-2 text-left font-semibold">Metric</th>
                      <th className="px-3 py-2 text-right font-semibold">Baseline</th>
                      <th className="px-3 py-2 text-right font-semibold">Scenario</th>
                      <th className="px-3 py-2 text-right font-semibold">Δ%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.kpi_deltas.map((k) => {
                      const st = deltaStatus(k.delta, k.good_direction);
                      return (
                        <tr key={k.name} className="border-t dark:border-slate-700">
                          <td className="px-3 py-2 text-left">{prettyName(k.name)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{fmt(k.baseline, k.unit)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmt(k.scenario, k.unit)}</td>
                          <td className={`px-3 py-2 text-right font-semibold tabular-nums ${STATUS_TEXT[st]}`}>
                            {k.pct === null ? "—" : `${k.pct > 0 ? "+" : ""}${k.pct.toFixed(1)}%`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
