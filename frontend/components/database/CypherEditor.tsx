"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { EditorView, keymap, placeholder } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { oneDark } from "@codemirror/theme-one-dark";
import { bracketMatching, indentOnInput } from "@codemirror/language";
import { searchKeymap } from "@codemirror/search";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { cypherLanguage } from "@/lib/cypher-lang";
import { useDatabaseStore } from "@/stores/databaseStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiUrl } from "@/lib/backend";
import { Play, Trash2, AlignLeft, Clock } from "lucide-react";

// ─── Cypher formatter ───────────────────────────────────────────────────────

const CYPHER_CLAUSE_RE =
  /\b(MATCH|OPTIONAL MATCH|WHERE|WITH|RETURN|ORDER BY|SKIP|LIMIT|CREATE|MERGE|DELETE|DETACH DELETE|SET|REMOVE|UNWIND|CALL|YIELD|UNION)\b/gi;

function formatCypher(query: string): string {
  const normalized = query.replace(/\s+/g, " ").trim();
  return normalized.replace(CYPHER_CLAUSE_RE, (m) => `\n${m.toUpperCase()}`).trim();
}

// ─── Light theme for CodeMirror ─────────────────────────────────────────────

const lightTheme = EditorView.theme({
  "&": {
    backgroundColor: "hsl(var(--background))",
    color: "hsl(var(--foreground))",
  },
  ".cm-gutters": {
    backgroundColor: "hsl(var(--muted))",
    borderRight: "1px solid hsl(var(--border))",
  },
  ".cm-activeLineGutter": {
    backgroundColor: "hsl(var(--accent))",
  },
  ".cm-activeLine": {
    backgroundColor: "hsl(var(--accent) / 0.5)",
  },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "hsl(var(--primary) / 0.15)",
  },
  ".cm-cursor": {
    borderLeftColor: "hsl(var(--foreground))",
  },
});

// ─── Component ──────────────────────────────────────────────────────────────

export function CypherEditor() {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);

  const currentQuery = useDatabaseStore((s) => s.currentQuery);
  const setQuery = useDatabaseStore((s) => s.setQuery);
  const isExecuting = useDatabaseStore((s) => s.isExecuting);
  const results = useDatabaseStore((s) => s.results);
  const setResults = useDatabaseStore((s) => s.setResults);
  const setExecuting = useDatabaseStore((s) => s.setExecuting);
  const addToHistory = useDatabaseStore((s) => s.addToHistory);
  const theme = useSettingsStore((s) => s.theme);

  const [execTime, setExecTime] = useState<number | null>(null);

  // Track the latest currentQuery to detect external changes (SSE)
  const lastExternalQuery = useRef(currentQuery);

  // Resolve whether dark mode
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  // ── Initialize CodeMirror ───────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        const value = update.state.doc.toString();
        lastExternalQuery.current = value;
        setQuery(value);
      }
    });

    const themeExt = isDark ? oneDark : lightTheme;

    const state = EditorState.create({
      doc: currentQuery,
      extensions: [
        cypherLanguage,
        themeExt,
        history(),
        bracketMatching(),
        closeBrackets(),
        indentOnInput(),
        placeholder("MATCH (n) RETURN n LIMIT 25"),
        keymap.of([
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
          ...closeBracketsKeymap,
        ]),
        updateListener,
        EditorView.lineWrapping,
        EditorView.theme({
          "&": { fontSize: "13px", maxHeight: "100%" },
          ".cm-scroller": { overflow: "auto" },
          ".cm-content": { padding: "8px 0" },
          ".cm-gutters": { display: "none" },
        }),
      ],
    });

    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Recreate editor when theme changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark]);

  // ── Sync external changes into the editor ─────────────────────────────

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;

    // Only update if the change came from outside (e.g. SSE cypher_query event)
    if (currentQuery !== lastExternalQuery.current) {
      lastExternalQuery.current = currentQuery;
      view.dispatch({
        changes: {
          from: 0,
          to: view.state.doc.length,
          insert: currentQuery,
        },
      });
    }
  }, [currentQuery]);

  // ── Execute query ─────────────────────────────────────────────────────

  const handleRun = useCallback(async () => {
    const query = viewRef.current?.state.doc.toString().trim();
    if (!query || isExecuting) return;

    setExecuting(true);
    setExecTime(null);
    const startTime = performance.now();

    try {
      const res = await fetch(apiUrl("/api/cypher"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, format: "both" }),
      });
      const data = await res.json();
      const elapsed = Math.round(performance.now() - startTime);

      const result = {
        query,
        columns: data.columns ?? [],
        rows: data.results ?? data.rows ?? [],
        executionTimeMs: data.execution_time_ms ?? elapsed,
        error: data.error,
        truncated: data.truncated,
        source: data.source,
        validationWarnings: data.validation_warnings ?? [],
        graph: data.graph ?? null,
        graphTruncated: data.graph_truncated,
        graphWarnings: data.graph_warnings ?? [],
      };

      setResults(result);
      addToHistory(result);
      setExecTime(elapsed);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setResults({
        query,
        columns: [],
        rows: [],
        error: msg,
      });
    } finally {
      setExecuting(false);
    }
  }, [isExecuting, setExecuting, setResults, addToHistory]);

  // ── Clear editor ──────────────────────────────────────────────────────

  const handleClear = useCallback(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: "" },
    });
    setQuery("");
    setResults(null);
    setExecTime(null);
  }, [setQuery, setResults]);

  // ── Format query ──────────────────────────────────────────────────────

  const handleFormat = useCallback(() => {
    const view = viewRef.current;
    if (!view) return;
    const formatted = formatCypher(view.state.doc.toString());
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: formatted },
    });
  }, []);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-1 border-b bg-muted/30 px-2 py-1.5">
        <Button
          size="sm"
          onClick={handleRun}
          disabled={isExecuting || !currentQuery.trim()}
          className="h-7 gap-1.5 bg-emerald-600 px-2.5 text-xs text-white hover:bg-emerald-700"
        >
          <Play className={cn("h-3 w-3", isExecuting && "animate-pulse")} />
          Run
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={handleFormat}
          className="h-7 px-2 text-xs"
          title="Format query"
        >
          <AlignLeft className="h-3.5 w-3.5" />
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={handleClear}
          className="h-7 px-2 text-xs"
          title="Clear editor"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>

        <div className="flex-1" />

        {/* Execution time */}
        {execTime !== null && (
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3" />
            {execTime}ms
          </span>
        )}

        {/* Row count */}
        {results && !results.error && (
          <span className="text-[11px] text-muted-foreground">
            {results.rows.length} row{results.rows.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Editor */}
      <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden" />

      {/* Error banner */}
      {results?.error && (
        <div className="border-t border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {results.error}
        </div>
      )}
    </div>
  );
}
