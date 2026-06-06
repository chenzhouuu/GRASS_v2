"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, subtitle, action, className }: EmptyStateProps) {
  return (
    <div className={cn(
      "flex flex-1 flex-col items-center justify-center gap-3 p-6 animate-in fade-in duration-200",
      className,
    )}>
      <div className="opacity-40">{icon}</div>
      <div className="text-center">
        <p className="text-base font-medium text-foreground">{title}</p>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Skeleton loading state for panels */
export function PanelSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-1 flex-col gap-3 p-4 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-4 w-4 rounded bg-muted" />
          <div className="h-4 flex-1 rounded bg-muted" />
          <div className="h-4 w-16 rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

/** Error state for panels */
export function PanelError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
      <p className="text-sm text-destructive">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-md bg-destructive/10 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/20 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
