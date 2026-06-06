"use client";

import { useCallback } from "react";
import { sendChatMessage } from "@/lib/api";
import { useChatStore } from "@/stores/chatStore";
import type { MapMarker } from "@/lib/types";

/**
 * Action buttons rendered inside each marker popup.
 * Adapts query text based on the entity type for more relevant results.
 */
export function MapPopupActions({ marker }: { marker: MapMarker }) {
  const isStreaming = useChatStore((s) => s.isStreaming);

  const send = useCallback(
    (message: string) => {
      if (isStreaming) return;
      sendChatMessage(message);
    },
    [isStreaming]
  );

  const entityType = (marker.type ?? "").toLowerCase();
  const label = marker.label;

  // Adapt "Nearby" query based on entity type
  const nearbyQuery =
    entityType === "farm" || entityType === "producer"
      ? `Find processors within 30 miles of ${label}`
      : entityType === "processor"
        ? `Find dairy farms that supply ${label}`
        : `Find entities within 30 miles of ${label}`;

  // Adapt "Routes" query based on entity type
  const routesQuery =
    entityType === "farm" || entityType === "producer"
      ? `Show supply routes from ${label} to processors`
      : entityType === "processor"
        ? `Show supply routes from farms to ${label}`
        : `Show all supply routes for ${label}`;

  return (
    <div className="mt-2 flex flex-wrap gap-1 border-t border-slate-200 pt-1.5">
      <button
        onClick={() => send(`Tell me more about ${label}`)}
        disabled={isStreaming}
        className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
      >
        Analyze
      </button>
      <button
        onClick={() => send(nearbyQuery)}
        disabled={isStreaming}
        className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
      >
        Nearby
      </button>
      <button
        onClick={() => send(routesQuery)}
        disabled={isStreaming}
        className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 hover:bg-amber-100 disabled:opacity-50"
      >
        Routes
      </button>
    </div>
  );
}
