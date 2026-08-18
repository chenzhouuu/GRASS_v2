import Link from "next/link";
import { Database } from "lucide-react";
import { OperationalDashboard } from "@/components/dashboard/OperationalDashboard";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { Button } from "@/components/ui/button";

export default function DashboardsPage() {
  return (
    <DashboardShell
      title="Supply Chain Dashboard"
      subtitle="Auto-generated from the connected Neo4j database"
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/dashboards/data-model">
            <Database className="h-4 w-4" />
            Data Model
          </Link>
        </Button>
      }
    >
      <OperationalDashboard />
    </DashboardShell>
  );
}
