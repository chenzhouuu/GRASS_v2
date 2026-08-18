"use client";

import { useState, useCallback, useEffect } from "react";
import { PanelLeftOpen } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { RightPanel } from "./RightPanel";
import { ThemeProvider } from "./ThemeProvider";
import { PanelErrorBoundary } from "./ErrorBoundary";
import { KeyboardHelp } from "./KeyboardHelp";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { OnboardingOverlay } from "@/components/onboarding/OnboardingOverlay";
import { applyDashboardDrilldown } from "@/lib/dashboardDrilldown";
import { fetchNeo4jConfig } from "@/lib/neo4j";
import { useAppStore } from "@/stores/appStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { usePreferencesSync } from "@/hooks/usePreferencesSync";
import { Toaster } from "sonner";
import { cn } from "@/lib/utils";

function AppContent() {
  const [helpOpen, setHelpOpen] = useState(false);
  const setNeo4jConnected = useAppStore((s) => s.setNeo4jConnected);
  const setDatabase = useSettingsStore((s) => s.setDatabase);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const setActiveTab = useAppStore((s) => s.setActiveRightTab);

  // ── Keyboard shortcuts ──────────────────────────────────────────────────
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const meta = e.metaKey || e.ctrlKey;
      if (!meta) return;

      switch (e.key.toLowerCase()) {
        case "b":
          e.preventDefault();
          toggleSidebar();
          break;
        case "k":
          e.preventDefault();
          document.querySelector<HTMLInputElement>('[placeholder="Search sessions..."]')?.focus();
          break;
        case "n":
          e.preventDefault();
          // Trigger new session — find the + button
          document.querySelector<HTMLButtonElement>('[data-action="new-session"]')?.click();
          break;
        case "1":
          e.preventDefault();
          setActiveTab("agent");
          break;
        case "2":
          e.preventDefault();
          setActiveTab("map");
          break;
        case "3":
          e.preventDefault();
          setActiveTab("data");
          break;
        case "4":
          e.preventDefault();
          setActiveTab("charts");
          break;
        case "/":
          if (e.shiftKey) {
            e.preventDefault();
            setHelpOpen(true);
          }
          break;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar, setActiveTab]);

  usePreferencesSync();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const rightTab = params.get("rightTab");
    const cypher = params.get("cypher");
    if (rightTab && cypher) {
      applyDashboardDrilldown({ rightTab, cypher });
      window.history.replaceState({}, "", "/");
    }
  }, []);

  // ── Neo4j connection check on mount ─────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    void fetchNeo4jConfig()
      .then((config) => {
        if (cancelled) return;
        setDatabase({
          uri: config.uri,
          username: config.username,
          password: config.password,
          database: config.database,
        });
        setNeo4jConnected(config.connected);
      })
      .catch(() => {
        if (cancelled) return;
        setNeo4jConnected(false);
      });
    return () => { cancelled = true; };
  }, [setDatabase, setNeo4jConnected]);

  return (
    <div className="flex h-screen min-h-0">
      {/* ── Sidebar (desktop) ──────────────────────────────────────────── */}
      <div
        className={cn(
          "hidden md:flex shrink-0 transition-[width] duration-200 ease-in-out overflow-hidden",
          sidebarOpen ? "w-[260px]" : "w-0"
        )}
      >
        <div className="w-[260px] min-w-[260px]">
          <Sidebar />
        </div>
      </div>

      {/* ── Sidebar collapse toggle (when closed) ─────────────────────── */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="hidden md:flex fixed top-3 left-3 z-40 items-center justify-center h-8 w-8 rounded-md bg-card border shadow-sm hover:bg-muted transition-colors"
          title="Open sidebar (⌘B)"
        >
          <PanelLeftOpen className="h-4 w-4 text-muted-foreground" />
        </button>
      )}

      {/* ── Main content area ──────────────────────────────────────────── */}
      <div className="flex min-h-0 min-w-0 flex-1">
        {/* Chat panel (flexible width) */}
        <div className="flex-1 min-w-0">
          <PanelErrorBoundary name="Chat">
            <ChatPanel />
          </PanelErrorBoundary>
        </div>

        {/* Vertical divider */}
        <div className="hidden md:block w-px bg-border shrink-0" />

        {/* Right panel (380px default, hidden on mobile) */}
        <div className="hidden md:flex w-[380px] shrink-0 h-full">
          <RightPanel />
        </div>
      </div>

      {/* ── Mobile sidebar overlay ─────────────────────────────────────── */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={toggleSidebar}
          />
          <div className="absolute left-0 top-0 bottom-0 w-[260px] animate-in slide-in-from-left duration-200">
            <Sidebar />
          </div>
        </div>
      )}

      {/* ── Floating elements ──────────────────────────────────────────── */}
      <SettingsDialog />
      <OnboardingOverlay />
      <KeyboardHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  );
}

export function AppShell() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}
