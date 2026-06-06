"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check } from "lucide-react";
import { useState, useCallback } from "react";
import type { Message } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  message: Message;
}

export const MessageBubble = memo(function MessageBubble({
  message,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(message.content).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => {
        // Clipboard API may fail in insecure contexts — ignore silently
      },
    );
  }, [message.content]);

  return (
    <div
      className={cn("group flex gap-3", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "relative max-w-[85%] rounded-lg px-4 py-2.5",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:my-2 prose-pre:my-2 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-code:before:content-none prose-code:after:content-none prose-code:rounded prose-code:bg-background/50 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        <button
          onClick={handleCopy}
          className={cn(
            "absolute -bottom-3 right-2 rounded-md border bg-background p-1 shadow-sm transition-opacity",
            "opacity-0 group-hover:opacity-100",
            isUser && "border-primary-foreground/20"
          )}
          aria-label="Copy message"
        >
          {copied ? (
            <Check className="h-3 w-3 text-muted-foreground" />
          ) : (
            <Copy className="h-3 w-3 text-muted-foreground" />
          )}
        </button>
      </div>
    </div>
  );
});
