"use client";

import { useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";
import { DashboardCardShell } from "@/components/dashboard/DashboardCardShell";
import { countMapPointsByType, dashboardRowsToMapPoints } from "@/lib/dashboardMap";
import { useDashboardStore } from "@/stores/dashboardStore";
import type { DashboardCardDefinition } from "@/lib/types";

const FacilityLeafletMap = dynamic(
  () => import("./FacilityLeafletMap").then((mod) => mod.FacilityLeafletMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[340px] items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground">
        Loading map...
      </div>
    ),
  },
);

function readCenter(display: Record<string, unknown> | undefined): [number, number] {
  const center = display?.center;
  if (Array.isArray(center) && center.length >= 2) {
    const lat = Number(center[0]);
    const lng = Number(center[1]);
    if (Number.isFinite(lat) && Number.isFinite(lng)) return [lat, lng];
  }
  return [40.9, -77.7];
}

function readZoom(display: Record<string, unknown> | undefined): number {
  const zoom = Number(display?.zoom);
  return Number.isFinite(zoom) ? zoom : 6;
}

export function MapCardLive({ card }: { card: DashboardCardDefinition }) {
  const result = useDashboardStore((s) => s.cardResults[card.id]);
  const executing = useDashboardStore((s) => s.executingCards.has(card.id));
  const executeCard = useDashboardStore((s) => s.executeCard);

  useEffect(() => {
    void executeCard(card);
  }, [card, executeCard]);

  const points = useMemo(
    () => dashboardRowsToMapPoints(result?.rows ?? []),
    [result?.rows],
  );
  const countsByType = useMemo(() => countMapPointsByType(points), [points]);

  return (
    <DashboardCardShell card={card} result={result} loading={executing && !result}>
      {points.length === 0 && result?.status === "success" ? (
        <p className="text-sm text-muted-foreground">No coordinate rows returned.</p>
      ) : (
        <div className="space-y-3">
          <FacilityLeafletMap
            points={points}
            center={readCenter(card.display)}
            zoom={readZoom(card.display)}
          />
          <div className="flex flex-wrap gap-2">
            {countsByType.map(([type, count]) => (
              <span key={type} className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                <MapPin className="h-3 w-3 text-primary" />
                {type}: {count.toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      )}
    </DashboardCardShell>
  );
}
