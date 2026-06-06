"use client";

import { Button } from "@/components/ui/button";
import { Settings, Moon, Sun } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";

export function Header() {
  const openSettings = useSettingsStore((s) => s.setOpen);
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);

  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  function toggleTheme() {
    setTheme(isDark ? "light" : "dark");
  }

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900 px-4">
      <div className="flex items-center gap-3">
        <span className="text-xl font-bold tracking-tight text-emerald-700 dark:text-emerald-400">GRASS</span>
        <span className="hidden text-sm text-slate-500 dark:text-slate-400 sm:inline">
          Supply Chain Analytics
        </span>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={toggleTheme}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {isDark ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => openSettings(true)}
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
