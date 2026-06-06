"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useDatabaseStore } from "@/stores/databaseStore";
import { Button } from "@/components/ui/button";
import {
  ChevronRight,
  ChevronDown,
  Tag,
  Link2,
  Search,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiUrl } from "@/lib/backend";
import type { SchemaNode, SchemaRelationship } from "@/lib/types";

// ─── Helpers ────────────────────────────────────────────────────────────────

function insertTextIntoQuery(current: string, text: string) {
  // If the editor is empty, replace entirely; otherwise append at end
  if (!current.trim()) return text;
  return current.trimEnd() + " " + text;
}

// ─── Collapsible section ────────────────────────────────────────────────────

function SectionHeader({
  label,
  count,
  open,
  onToggle,
  icon: Icon,
}: {
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  icon: React.ElementType;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs font-semibold text-muted-foreground hover:bg-muted/50"
    >
      {open ? (
        <ChevronDown className="h-3 w-3 shrink-0" />
      ) : (
        <ChevronRight className="h-3 w-3 shrink-0" />
      )}
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
      <span className="ml-auto text-[10px] font-normal tabular-nums text-muted-foreground/60">
        {count}
      </span>
    </button>
  );
}

// ─── Node item ──────────────────────────────────────────────────────────────

function NodeItem({
  node,
  onClickLabel,
  onClickProperty,
}: {
  node: SchemaNode;
  onClickLabel: (label: string) => void;
  onClickProperty: (label: string, property: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        onDoubleClick={() => onClickLabel(node.label)}
        className="group flex w-full items-center gap-1.5 px-4 py-1 text-left text-xs hover:bg-muted/40"
        title={`Double-click to insert MATCH (n:${node.label})`}
      >
        {open ? (
          <ChevronDown className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
        )}
        <Tag className="h-3 w-3 shrink-0 text-emerald-500" />
        <span className="truncate font-medium">{node.label}</span>
        <span className="ml-auto text-[10px] text-muted-foreground/60">
          {node.properties.length}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onClickLabel(node.label);
          }}
          className="ml-1 hidden rounded px-1 text-[10px] text-primary hover:bg-primary/10 group-hover:inline-block"
          title={`Insert MATCH (n:${node.label})`}
        >
          MATCH
        </button>
      </button>

      {open && node.properties.length > 0 && (
        <div className="ml-6 border-l border-border/40 pl-2">
          {node.properties.map((prop) => (
            <button
              key={prop}
              onClick={() => onClickProperty(node.label, prop)}
              className="flex w-full items-center gap-1.5 px-2 py-0.5 text-left text-[11px] text-muted-foreground hover:bg-muted/30 hover:text-foreground"
              title={`Insert n.${prop}`}
            >
              <span className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
              <span className="truncate">{prop}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Relationship item ──────────────────────────────────────────────────────

function RelationshipItem({
  rel,
  onClickType,
  onClickProperty,
}: {
  rel: SchemaRelationship;
  onClickType: (type: string) => void;
  onClickProperty: (type: string, property: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        onDoubleClick={() => onClickType(rel.type)}
        className="group flex w-full items-center gap-1.5 px-4 py-1 text-left text-xs hover:bg-muted/40"
        title={`Double-click to insert -[:${rel.type}]->`}
      >
        {rel.properties.length > 0 ? (
          open ? (
            <ChevronDown className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
          )
        ) : (
          <span className="h-2.5 w-2.5 shrink-0" />
        )}
        <Link2 className="h-3 w-3 shrink-0 text-amber-400" />
        <span className="truncate font-medium">{rel.type}</span>
        {rel.properties.length > 0 && (
          <span className="ml-auto text-[10px] text-muted-foreground/60">
            {rel.properties.length}
          </span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onClickType(rel.type);
          }}
          className="ml-1 hidden rounded px-1 text-[10px] text-primary hover:bg-primary/10 group-hover:inline-block"
          title={`Insert -[:${rel.type}]->`}
        >
          REL
        </button>
      </button>

      {open && rel.properties.length > 0 && (
        <div className="ml-6 border-l border-border/40 pl-2">
          {rel.properties.map((prop) => (
            <button
              key={prop}
              onClick={() => onClickProperty(rel.type, prop)}
              className="flex w-full items-center gap-1.5 px-2 py-0.5 text-left text-[11px] text-muted-foreground hover:bg-muted/30 hover:text-foreground"
              title={`Insert r.${prop}`}
            >
              <span className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
              <span className="truncate">{prop}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function SchemaExplorer() {
  const schema = useDatabaseStore((s) => s.schema);
  const schemaLoading = useDatabaseStore((s) => s.schemaLoading);
  const setSchema = useDatabaseStore((s) => s.setSchema);
  const setSchemaLoading = useDatabaseStore((s) => s.setSchemaLoading);
  const currentQuery = useDatabaseStore((s) => s.currentQuery);
  const setQuery = useDatabaseStore((s) => s.setQuery);

  const [searchTerm, setSearchTerm] = useState("");
  const [nodesOpen, setNodesOpen] = useState(true);
  const [relsOpen, setRelsOpen] = useState(true);

  // ── Fetch schema on mount ───────────────────────────────────────────────

  const fetchSchema = useCallback(async () => {
    setSchemaLoading(true);
    try {
      const res = await fetch(apiUrl("/api/schema"));
      if (!res.ok) throw new Error("Failed to fetch schema");
      const data = await res.json();
      setSchema(data);
    } catch {
      // Schema fetch failed — leave as null
      setSchema(null);
    } finally {
      setSchemaLoading(false);
    }
  }, [setSchema, setSchemaLoading]);

  useEffect(() => {
    if (!schema && !schemaLoading) {
      fetchSchema();
    }
  }, [schema, schemaLoading, fetchSchema]);

  // ── Filter schema by search term ────────────────────────────────────────

  const filteredNodes = useMemo(() => {
    if (!schema) return [];
    if (!searchTerm.trim()) return schema.nodes;
    const q = searchTerm.toLowerCase();
    return schema.nodes.filter(
      (n) =>
        n.label.toLowerCase().includes(q) ||
        n.properties.some((p) => p.toLowerCase().includes(q))
    );
  }, [schema, searchTerm]);

  const filteredRels = useMemo(() => {
    if (!schema) return [];
    if (!searchTerm.trim()) return schema.relationships;
    const q = searchTerm.toLowerCase();
    return schema.relationships.filter(
      (r) =>
        r.type.toLowerCase().includes(q) ||
        r.properties.some((p) => p.toLowerCase().includes(q))
    );
  }, [schema, searchTerm]);

  // ── Click handlers for inserting into editor ────────────────────────────

  const handleClickNodeLabel = useCallback(
    (label: string) => {
      const template = `MATCH (n:${label}) RETURN n LIMIT 25`;
      setQuery(insertTextIntoQuery(currentQuery, template));
    },
    [currentQuery, setQuery]
  );

  const handleClickNodeProperty = useCallback(
    (label: string, property: string) => {
      const snippet = `n.${property}`;
      setQuery(insertTextIntoQuery(currentQuery, snippet));
    },
    [currentQuery, setQuery]
  );

  const handleClickRelType = useCallback(
    (type: string) => {
      const snippet = `-[:${type}]->`;
      setQuery(insertTextIntoQuery(currentQuery, snippet));
    },
    [currentQuery, setQuery]
  );

  const handleClickRelProperty = useCallback(
    (type: string, property: string) => {
      const snippet = `r.${property}`;
      setQuery(insertTextIntoQuery(currentQuery, snippet));
    },
    [currentQuery, setQuery]
  );

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header + search */}
      <div className="flex flex-col gap-1.5 border-b bg-muted/30 px-2 py-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold">Schema</span>
          <div className="flex-1" />
          <Button
            size="sm"
            variant="ghost"
            onClick={fetchSchema}
            disabled={schemaLoading}
            className="h-6 w-6 p-0"
            title="Refresh schema"
          >
            <RefreshCw
              className={cn("h-3 w-3", schemaLoading && "animate-spin")}
            />
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Filter labels, types, properties..."
            className="h-7 w-full rounded border border-border bg-background pl-7 pr-2 text-xs placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {/* Tree content */}
      <div className="min-h-0 flex-1 overflow-y-auto" style={{ overflowY: "scroll", scrollbarGutter: "stable" }}>
        {schemaLoading && !schema && (
          <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading schema...
          </div>
        )}

        {!schemaLoading && !schema && (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            Failed to load schema.
            <br />
            <button
              onClick={fetchSchema}
              className="mt-1 text-primary hover:underline"
            >
              Retry
            </button>
          </div>
        )}

        {schema && (
          <>
            {/* Nodes section */}
            <SectionHeader
              label="Nodes"
              count={filteredNodes.length}
              open={nodesOpen}
              onToggle={() => setNodesOpen(!nodesOpen)}
              icon={Tag}
            />
            {nodesOpen && (
              <div>
                {filteredNodes.length === 0 ? (
                  <div className="px-4 py-2 text-[11px] text-muted-foreground/60">
                    No matches
                  </div>
                ) : (
                  filteredNodes.map((node) => (
                    <NodeItem
                      key={node.label}
                      node={node}
                      onClickLabel={handleClickNodeLabel}
                      onClickProperty={handleClickNodeProperty}
                    />
                  ))
                )}
              </div>
            )}

            {/* Relationships section */}
            <SectionHeader
              label="Relationships"
              count={filteredRels.length}
              open={relsOpen}
              onToggle={() => setRelsOpen(!relsOpen)}
              icon={Link2}
            />
            {relsOpen && (
              <div>
                {filteredRels.length === 0 ? (
                  <div className="px-4 py-2 text-[11px] text-muted-foreground/60">
                    No matches
                  </div>
                ) : (
                  filteredRels.map((rel) => (
                    <RelationshipItem
                      key={rel.type}
                      rel={rel}
                      onClickType={handleClickRelType}
                      onClickProperty={handleClickRelProperty}
                    />
                  ))
                )}
              </div>
            )}

            {/* Empty search state */}
            {searchTerm.trim() &&
              filteredNodes.length === 0 &&
              filteredRels.length === 0 && (
                <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                  No results for &quot;{searchTerm}&quot;
                </div>
              )}
          </>
        )}
      </div>
    </div>
  );
}
