"use client";

import { useEffect } from "react";
import { useSettingsStore } from "@/stores/settingsStore";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSettingsStore((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;

    function apply(mode: "light" | "dark") {
      root.classList.toggle("dark", mode === "dark");
    }

    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      apply(mq.matches ? "dark" : "light");

      const onChange = (e: MediaQueryListEvent) => {
        apply(e.matches ? "dark" : "light");
      };
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }

    apply(theme);
  }, [theme]);

  return <>{children}</>;
}
