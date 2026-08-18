import { useAppStore } from "@/stores/appStore";
import { useDatabaseStore } from "@/stores/databaseStore";

export function buildDrilldownUrl(cypher: string): string {
  const params = new URLSearchParams({
    rightTab: "data",
    cypher,
  });
  return `/?${params.toString()}`;
}

export function applyDashboardDrilldown(args: { rightTab: string; cypher: string }) {
  if (args.rightTab === "data" && args.cypher) {
    useDatabaseStore.getState().setQuery(args.cypher);
    useAppStore.getState().setActiveRightTab("data");
  }
}
