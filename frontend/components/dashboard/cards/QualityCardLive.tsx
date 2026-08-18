"use client";

import { KpiCardLive } from "@/components/dashboard/cards/KpiCardLive";
import type { DashboardCardDefinition } from "@/lib/types";

export function QualityCardLive({ card }: { card: DashboardCardDefinition }) {
  return <KpiCardLive card={card} />;
}
