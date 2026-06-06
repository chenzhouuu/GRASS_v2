"use client";

import { memo, useState, useCallback } from "react";
import { Copy, Check, Pencil } from "lucide-react";
import type { Message } from "@/lib/types";
import { cn } from "@/lib/utils";

interface UserMessageProps {
  message: Message;
}

export const UserMessage = memo(function UserMessage({ message }: UserMessageProps) {
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

  return (
    <div className="flex justify-end">
      <div className="group relative max-w-[85%]">
        <div className="rounded-2xl bg-muted/70 px-4 py-2.5">
          <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-foreground">
            {message.content}
          </p>
        </div>

        {/* Hover toolbar */}
        <div className={cn(
          "absolute -bottom-4 right-2 flex items-center gap-0.5",
          "rounded-lg border bg-background px-1 py-0.5 shadow-sm",
          "opacity-0 group-hover:opacity-100 transition-opacity",
        )}>
          <button
            onClick={handleCopy}
            className="rounded p-1 hover:bg-muted transition-colors"
            aria-label="Copy message"
          >
            {copied ? (
              <Check className="h-3 w-3 text-success" />
            ) : (
              <Copy className="h-3 w-3 text-muted-foreground" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
});
