"use client";

import { useEffect, useState } from "react";

const SHORTCUT_GROUPS = [
  {
    label: "Navigation",
    shortcuts: [
      { keys: ["mod", "B"], desc: "Toggle sidebar" },
      { keys: ["mod", "K"], desc: "Search sessions" },
      { keys: ["mod", "N"], desc: "New session" },
      { keys: ["Esc"], desc: "Close overlay" },
    ],
  },
  {
    label: "Chat",
    shortcuts: [
      { keys: ["mod", "Enter"], desc: "Send message" },
    ],
  },
  {
    label: "Right panel",
    shortcuts: [
      { keys: ["mod", "1"], desc: "Agent tab" },
      { keys: ["mod", "2"], desc: "Map tab" },
      { keys: ["mod", "3"], desc: "Data tab" },
      { keys: ["mod", "4"], desc: "Charts tab" },
    ],
  },
  {
    label: "Other",
    shortcuts: [
      { keys: ["mod", "?"], desc: "Keyboard shortcuts" },
    ],
  },
];

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex h-5 min-w-[20px] items-center justify-center rounded border bg-muted px-1.5 text-2xs font-medium text-muted-foreground">
      {children}
    </kbd>
  );
}

export function ShortcutsTab() {
  const [isMac, setIsMac] = useState(false);
  useEffect(() => {
    setIsMac(navigator.platform?.includes("Mac") ?? false);
  }, []);

  const mod = isMac ? "\u2318" : "Ctrl";

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[14px] font-semibold">Keyboard shortcuts</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Quick actions available anywhere in the application.
        </p>
      </div>

      {SHORTCUT_GROUPS.map((group) => (
        <div key={group.label} className="space-y-2">
          <p className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </p>
          <div className="space-y-1">
            {group.shortcuts.map((s) => (
              <div
                key={s.desc}
                className="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-muted/50 transition-colors"
              >
                <span className="text-sm">{s.desc}</span>
                <div className="flex items-center gap-1">
                  {s.keys.map((k, i) => (
                    <Kbd key={i}>{k === "mod" ? mod : k}</Kbd>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
