"use client";

import { useCallback } from "react";
import { Clipboard, MessageSquare, X, TerminalSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useChatStore } from "@/stores/chatStore";
import { useDatabaseStore } from "@/stores/databaseStore";
import type { NvlGraphNode, NvlGraphRelationship } from "@/lib/types";

export type GraphSelection =
  | { kind: "node"; entity: NvlGraphNode }
  | { kind: "relationship"; entity: NvlGraphRelationship };

function formatValue(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function escapeCypherString(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

export function GraphInspector({
  selection,
  onClose,
}: {
  selection: GraphSelection;
  onClose: () => void;
}) {
  const setQuery = useDatabaseStore((s) => s.setQuery);
  const setInputDraft = useChatStore((s) => s.setInputDraft);

  const isNode = selection.kind === "node";
  const entity = selection.entity;
  const title = entity.caption || entity.id;
  const properties = entity.properties ?? {};
  const badges = isNode
    ? (entity as NvlGraphNode).labels ?? []
    : [(entity as NvlGraphRelationship).type || "Relationship"];

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(JSON.stringify(entity, null, 2));
  }, [entity]);

  const handleInsertQuery = useCallback(() => {
    if (selection.kind === "node") {
      const label = selection.entity.labels?.[0];
      const labelClause = label ? `:${label}` : "";
      setQuery(
        `MATCH (n${labelClause}) WHERE elementId(n) = '${escapeCypherString(selection.entity.id)}' RETURN n LIMIT 25`,
      );
      return;
    }
    const type = selection.entity.type ? `:${selection.entity.type}` : "";
    setQuery(
      `MATCH ()-[r${type}]->() WHERE elementId(r) = '${escapeCypherString(selection.entity.id)}' RETURN r LIMIT 25`,
    );
  }, [selection, setQuery]);

  const handleAskChat = useCallback(() => {
    setInputDraft(
      `Explain this Neo4j ${selection.kind} from the graph results:\n${JSON.stringify(entity, null, 2)}`,
    );
  }, [entity, selection.kind, setInputDraft]);

  return (
    <aside className="absolute right-2 top-2 z-20 flex max-h-[calc(100%-1rem)] w-72 flex-col overflow-hidden rounded-lg border bg-background/95 shadow-lg backdrop-blur">
      <div className="flex items-start gap-2 border-b px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{title}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {badges.map((badge) => (
              <Badge key={badge} variant="secondary" className="px-1.5 py-0 text-[10px]">
                {badge}
              </Badge>
            ))}
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onClose}
          className="h-7 w-7 shrink-0 p-0"
          aria-label="Close graph inspector"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-3 py-2">
        <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
          Element ID
        </div>
        <div className="mb-3 break-all rounded border bg-muted/30 p-2 font-mono text-[10px] text-muted-foreground">
          {entity.id}
        </div>

        <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">
          Properties
        </div>
        {Object.keys(properties).length === 0 ? (
          <p className="text-xs text-muted-foreground">No properties on this element.</p>
        ) : (
          <div className="divide-y rounded border">
            {Object.entries(properties).map(([key, value]) => (
              <div key={key} className="grid grid-cols-[6rem_1fr] gap-2 px-2 py-1.5 text-xs">
                <span className="truncate font-mono text-muted-foreground">{key}</span>
                <span className="min-w-0 break-words">{formatValue(value)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1 border-t bg-muted/20 p-2">
        <Button size="sm" variant="ghost" onClick={handleInsertQuery} className="h-7 gap-1 px-2 text-xs">
          <TerminalSquare className="h-3.5 w-3.5" />
          Insert
        </Button>
        <Button size="sm" variant="ghost" onClick={handleAskChat} className="h-7 gap-1 px-2 text-xs">
          <MessageSquare className="h-3.5 w-3.5" />
          Chat
        </Button>
        <Button size="sm" variant="ghost" onClick={handleCopy} className="h-7 gap-1 px-2 text-xs">
          <Clipboard className="h-3.5 w-3.5" />
          Copy
        </Button>
      </div>
    </aside>
  );
}
