import Link from "next/link";
import { LayoutDashboard } from "lucide-react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { DataModelDashboard } from "@/components/dashboard/DataModelDashboard";
import { Button } from "@/components/ui/button";

export default function DashboardDataModelPage() {
  return (
    <DashboardShell
      title="Data Model"
      subtitle="Advanced Neo4j schema, relationship, property, and sample graph diagnostics"
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/dashboards">
            <LayoutDashboard className="h-4 w-4" />
            Dashboard
          </Link>
        </Button>
      }
    >
      <DataModelDashboard />
    </DashboardShell>
  );
}
