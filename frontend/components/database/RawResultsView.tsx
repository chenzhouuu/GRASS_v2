"use client";

import { useMemo, useState, useCallback } from "react";
import { Clipboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CypherResult } from "@/lib/types";

export function RawResultsView({ results }: { results: CypherResult }) {
  const [copied, setCopied] = useState(false);
  const rawJson = useMemo(() => JSON.stringify(results, null, 2), [results]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(rawJson);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }, [rawJson]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b bg-muted/30 px-2 py-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Raw response payload
        </span>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleCopy}
          className="h-7 gap-1.5 px-2 text-xs"
        >
          <Clipboard className="h-3.5 w-3.5" />
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="min-h-0 flex-1 overflow-auto p-3 text-[11px] leading-5 text-muted-foreground">
        {rawJson}
      </pre>
    </div>
  );
}
