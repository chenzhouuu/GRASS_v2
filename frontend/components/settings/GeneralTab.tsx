"use client";

import { Sun, Moon, Monitor, FileText, Table, Braces } from "lucide-react";
import {
  useSettingsStore,
  type Theme,
  type ExportFormat,
} from "@/stores/settingsStore";
import { cn } from "@/lib/utils";

// ─── Section wrapper ─────────────────────────────────────────────────────────

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[14px] font-semibold text-foreground">{title}</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}

// ─── Selection card ──────────────────────────────────────────────────────────

function OptionCard({
  selected,
  onClick,
  icon: Icon,
  label,
  description,
}: {
  selected: boolean;
  onClick: () => void;
  icon: React.ElementType;
  label: string;
  description?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-1 flex-col items-center gap-2 rounded-xl border-2 p-4 text-center transition-all",
        selected
          ? "border-primary bg-accent-subtle text-primary"
          : "border-transparent bg-muted/40 text-muted-foreground hover:border-border hover:bg-muted/60"
      )}
    >
      <Icon className="h-5 w-5" />
      <div>
        <p className="text-sm font-medium">{label}</p>
        {description && (
          <p className="mt-0.5 text-2xs opacity-70">{description}</p>
        )}
      </div>
    </button>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export function GeneralTab() {
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const exportFormat = useSettingsStore((s) => s.exportFormat);
  const setExportFormat = useSettingsStore((s) => s.setExportFormat);

  return (
    <div className="space-y-8">
      <Section
        title="Appearance"
        description="Choose how GRASS looks on your device."
      >
        <div className="flex gap-2.5">
          <OptionCard
            selected={theme === "light"}
            onClick={() => setTheme("light")}
            icon={Sun}
            label="Light"
          />
          <OptionCard
            selected={theme === "dark"}
            onClick={() => setTheme("dark")}
            icon={Moon}
            label="Dark"
          />
          <OptionCard
            selected={theme === "system"}
            onClick={() => setTheme("system")}
            icon={Monitor}
            label="System"
            description="Follows OS"
          />
        </div>
      </Section>

      <div className="h-px bg-border" />

      <Section
        title="Export format"
        description="Default format when downloading data and reports."
      >
        <div className="flex gap-2.5">
          <OptionCard
            selected={exportFormat === "pdf"}
            onClick={() => setExportFormat("pdf")}
            icon={FileText}
            label="PDF"
          />
          <OptionCard
            selected={exportFormat === "csv"}
            onClick={() => setExportFormat("csv")}
            icon={Table}
            label="CSV"
          />
          <OptionCard
            selected={exportFormat === "json"}
            onClick={() => setExportFormat("json")}
            icon={Braces}
            label="JSON"
          />
        </div>
      </Section>
    </div>
  );
}
