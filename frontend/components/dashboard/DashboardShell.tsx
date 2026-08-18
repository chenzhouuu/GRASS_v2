"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, LayoutDashboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import { cn } from "@/lib/utils";

interface DashboardShellProps {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function DashboardShell({
  title = "GRASS Dashboards",
  subtitle = "Supply-chain and agriculture insight workspaces",
  actions,
  children,
  className,
}: DashboardShellProps) {
  return (
    <ThemeProvider>
      <main className="min-h-screen bg-background text-foreground">
        <div className="mx-auto flex min-h-screen w-full max-w-[1600px] flex-col px-4 py-4 sm:px-6 lg:px-8">
          <header className="mb-5 flex flex-col gap-4 rounded-2xl border bg-card/80 p-4 shadow-sm backdrop-blur md:flex-row md:items-center md:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <LayoutDashboard className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
                <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {actions}
              <Button asChild variant="outline" size="sm">
                <Link href="/" aria-label="Back to GRASS app">
                  <ArrowLeft className="h-4 w-4" />
                  Back to App
                </Link>
              </Button>
            </div>
          </header>
          <section className={cn("min-h-0 flex-1", className)}>{children}</section>
        </div>
      </main>
    </ThemeProvider>
  );
}

