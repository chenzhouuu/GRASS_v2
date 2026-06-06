"use client";

import { Group, Panel, Separator } from "react-resizable-panels";
import { CypherEditor } from "./CypherEditor";
import { ResultsTable } from "./ResultsTable";
import { SchemaExplorer } from "./SchemaExplorer";

function ResizeHandle() {
  return (
    <Separator className="relative flex h-1 items-center justify-center bg-border transition-colors hover:bg-primary/20 data-[separator=active]:bg-primary/30">
      <div className="z-10 h-[3px] w-8 rounded-full bg-border transition-colors [[data-separator=active]>&]:bg-primary/50 [div:hover>&]:bg-muted-foreground/50" />
    </Separator>
  );
}

export function DatabasePanel() {
  return (
    <Group orientation="vertical" className="h-full min-h-0">
      {/* Schema explorer — top, collapsible */}
      <Panel defaultSize={30} minSize={10} collapsible collapsedSize={0}>
        <div className="h-full min-h-0 overflow-hidden rounded-md border">
          <SchemaExplorer />
        </div>
      </Panel>

      <ResizeHandle />

      {/* Cypher editor — middle */}
      <Panel defaultSize={30} minSize={15}>
        <div className="h-full min-h-0 overflow-hidden rounded-md border">
          <CypherEditor />
        </div>
      </Panel>

      <ResizeHandle />

      {/* Results table — bottom */}
      <Panel defaultSize={40} minSize={15}>
        <div className="h-full min-h-0 overflow-hidden rounded-md border">
          <ResultsTable />
        </div>
      </Panel>
    </Group>
  );
}
