"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import {
  Settings,
  Palette,
  Bot,
  KeyRound,
  Database,
  Map,
} from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { GeneralTab } from "./GeneralTab";
import { ModelsTab } from "./ModelsTab";
import { ApiKeysTab } from "./ApiKeysTab";
import { DatabaseTab } from "./DatabaseTab";
import { MapSettingsTab } from "./MapSettingsTab";
import { cn } from "@/lib/utils";

type SettingsPage = "general" | "models" | "apikeys" | "database" | "map";

const NAV_ITEMS: { id: SettingsPage; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: Palette },
  { id: "models", label: "Models", icon: Bot },
  { id: "apikeys", label: "API Keys", icon: KeyRound },
  { id: "database", label: "Database", icon: Database },
  { id: "map", label: "Map", icon: Map },
];

export function SettingsDialog() {
  const isOpen = useSettingsStore((s) => s.isOpen);
  const setOpen = useSettingsStore((s) => s.setOpen);
  const [activePage, setActivePage] = useState<SettingsPage>("general");

  return (
    <Dialog open={isOpen} onOpenChange={setOpen}>
      <DialogContent className="flex max-w-[720px] h-[85vh] max-h-[85vh] flex-col p-0 gap-0 overflow-hidden">
        {/* ── Header ──────────────────────────────────────────────── */}
        <div className="flex shrink-0 items-center border-b px-5 py-3.5">
          <Settings className="h-4 w-4 text-muted-foreground" />
          <h2 className="ml-2.5 text-[15px] font-semibold">Settings</h2>
        </div>

        {/* ── Body: sidebar + content ─────────────────────────────── */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Sidebar nav */}
          <nav className="w-[180px] shrink-0 border-r bg-muted/30 p-2">
            {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActivePage(id)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  activePage === id
                    ? "bg-background text-foreground font-medium shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </button>
            ))}
          </nav>

          {/* Content area — scrollable */}
          <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
            {activePage === "general" && <GeneralTab />}
            {activePage === "models" && <ModelsTab />}
            {activePage === "apikeys" && <ApiKeysTab />}
            {activePage === "database" && <DatabaseTab />}
            {activePage === "map" && <MapSettingsTab />}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
