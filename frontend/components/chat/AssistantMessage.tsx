"use client";

import { memo, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check, ThumbsUp, ThumbsDown } from "lucide-react";
import type { Message } from "@/lib/types";
import { InlineChart } from "./InlineChart";
import { ActionChips } from "./ActionChips";
import { cn } from "@/lib/utils";

interface AssistantMessageProps {
  message: Message;
  onSendMessage?: (message: string) => void;
}

export const AssistantMessage = memo(function AssistantMessage({
  message,
  onSendMessage,
}: AssistantMessageProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(message.content).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => {},
    );
  }, [message.content]);

  const hasMap = !!message.mapData?.markers?.length;
  const hasChart = !!message.visualizations?.some((v) => v.type === "chart");
  const hasData = !!message.mapData || hasChart;

  return (
    <div className="group relative">
      {/* Prose — flows naturally, no card/border/background */}
      {message.content && (
        <div className="prose prose-neutral dark:prose-invert max-w-none text-[14px] leading-[1.7] prose-p:my-2 prose-headings:my-3 prose-headings:font-semibold prose-h3:text-[15px] prose-pre:my-3 prose-pre:rounded-lg prose-pre:bg-muted prose-pre:border prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-code:before:content-none prose-code:after:content-none prose-code:rounded-md prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[13px] prose-code:font-normal prose-table:text-[13px] prose-th:bg-muted/50 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-strong:font-semibold prose-blockquote:border-l-primary/30 prose-blockquote:text-muted-foreground">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
      )}

      {/* Inline charts — flow naturally below prose */}
      {message.visualizations && message.visualizations.length > 0 && (
        <div className="mt-4 flex flex-col gap-3">
          {message.visualizations
            .filter((v) => v.type === "chart")
            .map((viz) => (
              <InlineChart key={viz.id} visualization={viz} />
            ))}
        </div>
      )}

      {/* Action chips */}
      <ActionChips
        hasMap={hasMap}
        hasChart={hasChart}
        hasData={hasData}
        onSendMessage={onSendMessage}
      />

      {/* Hover toolbar — appears below the message */}
      {message.content && (
        <div className={cn(
          "mt-1 flex items-center gap-0.5",
          "opacity-0 group-hover:opacity-100 transition-opacity",
        )}>
          <button
            onClick={handleCopy}
            className="rounded-md p-1.5 hover:bg-muted transition-colors"
            aria-label="Copy response"
            title="Copy"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-success" />
            ) : (
              <Copy className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>
        </div>
      )}
    </div>
  );
});
