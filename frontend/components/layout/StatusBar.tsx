"use client";

import React from "react";
import { Circle } from "lucide-react";
import { useAppStore } from "@/stores/appStore";

export function getNeo4jStatusLabel(connected: boolean): string {
  return connected ? "Neo4j: Connected" : "Neo4j: Not connected";
}

export function StatusBar() {
  const neo4jConnected = useAppStore((s) => s.neo4jConnected);

  return (
    <footer className="flex h-7 shrink-0 items-center justify-between border-t border-slate-200 bg-slate-50 px-4 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-1.5">
          <Circle className="h-2 w-2 fill-slate-400 text-slate-400" />
          Idle
        </span>
      </div>
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-1.5">
          <Circle
            className={`h-2 w-2 ${
              neo4jConnected
                ? "fill-emerald-500 text-emerald-500"
                : "fill-amber-500 text-amber-500"
            }`}
          />
          {getNeo4jStatusLabel(neo4jConnected)}
        </span>
        <span className="text-slate-500 dark:text-slate-400">Model: —</span>
      </div>
    </footer>
  );
}
