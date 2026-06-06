"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const isMac =
  typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);
const mod = isMac ? "\u2318" : "Ctrl+";

const SHORTCUTS = [
  { keys: `${mod}B`, desc: "Toggle sidebar" },
  { keys: `${mod}K`, desc: "Focus session search" },
  { keys: `${mod}N`, desc: "New session" },
  { keys: `${mod}Enter`, desc: "Send message" },
  { keys: `${mod}1`, desc: "Agent tab" },
  { keys: `${mod}2`, desc: "Map tab" },
  { keys: `${mod}3`, desc: "Data tab" },
  { keys: `${mod}4`, desc: "Charts tab" },
  { keys: `Escape`, desc: "Close overlay / deselect" },
  { keys: `${mod}?`, desc: "Show keyboard shortcuts" },
];

export function KeyboardHelp({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{s.desc}</span>
              <kbd className="rounded border bg-muted px-2 py-0.5 font-mono text-xs">
                {s.keys}
              </kbd>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
