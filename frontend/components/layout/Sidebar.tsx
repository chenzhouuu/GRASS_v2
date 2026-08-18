"use client";

import Link from "next/link";
import {
  useState,
  useCallback,
  useRef,
  useEffect,
  type MouseEvent,
  type KeyboardEvent,
} from "react";
import {
  Plus,
  Search,
  MessageSquare,
  Pencil,
  Trash2,
  X,
  Check,
  Settings,
  PanelLeftClose,
  LayoutDashboard,
} from "lucide-react";
import { useSessions } from "@/hooks/useSessions";
import { useAppStore } from "@/stores/appStore";
import { useSettingsStore } from "@/stores/settingsStore";
import type { Session } from "@/lib/types";
import { cn } from "@/lib/utils";

// ─── Relative time formatting ────────────────────────────────────────────────

function formatRelativeTime(epoch: number): string {
  const diff = Date.now() - epoch;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(epoch).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

// ─── Session grouping ────────────────────────────────────────────────────────

function getSessionGroup(epoch: number): string {
  const now = new Date();
  const date = new Date(epoch);
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterdayStart = todayStart - 86_400_000;
  const weekStart = todayStart - 7 * 86_400_000;

  if (epoch >= todayStart) return "Today";
  if (epoch >= yesterdayStart) return "Yesterday";
  if (epoch >= weekStart) return "This Week";
  return "Older";
}

function groupSessions(sessions: Session[]): { label: string; sessions: Session[] }[] {
  const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);
  const groups: Map<string, Session[]> = new Map();
  const order = ["Today", "Yesterday", "This Week", "Older"];

  for (const s of sorted) {
    const label = getSessionGroup(s.updatedAt);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(s);
  }

  return order
    .filter((label) => groups.has(label))
    .map((label) => ({ label, sessions: groups.get(label)! }));
}

// ─── Context menu ────────────────────────────────────────────────────────────

interface ContextMenuProps {
  x: number;
  y: number;
  session: Session;
  onRename: (session: Session) => void;
  onDelete: (session: Session) => void;
  onClose: () => void;
}

function ContextMenu({
  x,
  y,
  session,
  onRename,
  onDelete,
  onClose,
}: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: globalThis.MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function handleEsc(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[140px] rounded-md border border-sidebar-hover bg-sidebar-bg p-1 shadow-md animate-in fade-in-0 zoom-in-95"
      style={{ left: x, top: y }}
    >
      <button
        className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-sidebar-text hover:bg-sidebar-hover"
        onClick={() => { onRename(session); onClose(); }}
      >
        <Pencil className="h-3.5 w-3.5" />
        Rename
      </button>
      <button
        className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-red-400 hover:bg-red-500/10"
        onClick={() => { onDelete(session); onClose(); }}
      >
        <Trash2 className="h-3.5 w-3.5" />
        Delete
      </button>
    </div>
  );
}

// ─── Inline rename input ─────────────────────────────────────────────────────

function RenameInput({
  initialValue,
  onConfirm,
  onCancel,
}: {
  initialValue: string;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed && trimmed !== initialValue) {
      onConfirm(trimmed);
    } else {
      onCancel();
    }
  }, [value, initialValue, onConfirm, onCancel]);

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleSubmit}
        onKeyDown={(e: KeyboardEvent) => {
          if (e.key === "Enter") handleSubmit();
          if (e.key === "Escape") onCancel();
        }}
        className="h-6 flex-1 min-w-0 rounded border border-sidebar-hover bg-sidebar-bg px-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <button
        onMouseDown={(e) => e.preventDefault()}
        onClick={handleSubmit}
        className="shrink-0 rounded p-0.5 hover:bg-sidebar-hover"
        title="Confirm"
      >
        <Check className="h-3 w-3 text-primary" />
      </button>
      <button
        onMouseDown={(e) => e.preventDefault()}
        onClick={onCancel}
        className="shrink-0 rounded p-0.5 hover:bg-sidebar-hover"
        title="Cancel"
      >
        <X className="h-3 w-3 text-sidebar-text" />
      </button>
    </div>
  );
}

// ─── Session item ────────────────────────────────────────────────────────────

function SessionItem({
  session,
  isCurrent,
  isRenaming,
  onSelect,
  onContextMenu,
  onRenameConfirm,
  onRenameCancel,
}: {
  session: Session;
  isCurrent: boolean;
  isRenaming: boolean;
  onSelect: () => void;
  onContextMenu: (e: MouseEvent) => void;
  onRenameConfirm: (title: string) => void;
  onRenameCancel: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      onContextMenu={onContextMenu}
      className={cn(
        "group flex w-full flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left transition-colors",
        isCurrent
          ? "bg-primary text-white"
          : "text-sidebar-text hover:bg-sidebar-hover"
      )}
    >
      {isRenaming ? (
        <RenameInput
          initialValue={session.title}
          onConfirm={onRenameConfirm}
          onCancel={onRenameCancel}
        />
      ) : (
        <span className="w-full truncate text-sm font-medium">
          {session.title}
        </span>
      )}

      <div className="flex w-full items-center gap-1.5 text-2xs opacity-70">
        <span className="shrink-0">{formatRelativeTime(session.updatedAt)}</span>
        {session.messageCount > 0 && (
          <>
            <span>·</span>
            <span className="shrink-0">
              {session.messageCount} msg{session.messageCount !== 1 ? "s" : ""}
            </span>
          </>
        )}
      </div>
    </button>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

export function Sidebar() {
  const {
    sessions,
    currentSessionId,
    createSession,
    selectSession,
    deleteSession: doDelete,
    renameSession: doRename,
  } = useSessions();

  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const openSettings = useSettingsStore((s) => s.setOpen);

  const [search, setSearch] = useState("");
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    session: Session;
  } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);

  // Filter sessions by search keyword
  const filtered = search.trim()
    ? sessions.filter(
        (s) =>
          s.title.toLowerCase().includes(search.toLowerCase()) ||
          (s.lastMessagePreview ?? "")
            .toLowerCase()
            .includes(search.toLowerCase()),
      )
    : sessions;

  const grouped = groupSessions(filtered);

  const handleContextMenu = useCallback(
    (e: MouseEvent, session: Session) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, session });
    },
    [],
  );

  const handleRenameStart = useCallback((session: Session) => {
    setRenamingId(session.id);
  }, []);

  const handleRenameConfirm = useCallback(
    async (id: string, title: string) => {
      await doRename(id, title);
      setRenamingId(null);
    },
    [doRename],
  );

  const handleDelete = useCallback(
    async (session: Session) => {
      await doDelete(session.id);
    },
    [doDelete],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar-bg">
      {/* Header: compact wordmark + collapse */}
      <div className="flex shrink-0 items-center justify-between px-4 py-3">
        <span className="text-base font-bold tracking-tight text-white">
          GRASS
        </span>
        <button
          onClick={toggleSidebar}
          className="rounded p-1 text-sidebar-text hover:bg-sidebar-hover hover:text-white transition-colors"
          title="Collapse sidebar (⌘B)"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Search bar */}
      <div className="shrink-0 px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-sidebar-text" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions..."
            className="h-8 w-full rounded-md border border-sidebar-hover bg-sidebar-hover pl-8 pr-2 text-sm text-white placeholder:text-sidebar-text focus:outline-none focus:ring-1 focus:ring-primary"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 hover:bg-sidebar-active"
            >
              <X className="h-3 w-3 text-sidebar-text" />
            </button>
          )}
        </div>
      </div>

      {/* Session list — grouped */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 scrollbar-thin" style={{ scrollbarGutter: "stable" }}>
        {grouped.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 px-2 py-8 text-sidebar-text">
            <MessageSquare className="h-6 w-6 opacity-20" />
            <p className="text-sm text-center">
              {search ? "No matching sessions" : "No sessions yet"}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {grouped.map((group) => (
              <div key={group.label}>
                <p className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-sidebar-text/60">
                  {group.label}
                </p>
                <div className="space-y-0.5">
                  {group.sessions.map((session) => (
                    <SessionItem
                      key={session.id}
                      session={session}
                      isCurrent={session.id === currentSessionId}
                      isRenaming={session.id === renamingId}
                      onSelect={() => selectSession(session.id)}
                      onContextMenu={(e) => handleContextMenu(e, session)}
                      onRenameConfirm={(title) =>
                        handleRenameConfirm(session.id, title)
                      }
                      onRenameCancel={() => setRenamingId(null)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer: New session + Dashboards + Settings */}
      <div className="shrink-0 border-t border-sidebar-hover p-3 space-y-2">
        <button
          onClick={createSession}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-sidebar-text/30 px-3 py-2 text-sm text-primary hover:border-primary hover:bg-sidebar-hover transition-colors"
        >
          <Plus className="h-4 w-4" />
          New Session
        </button>
        <Link
          href="/dashboards"
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-sidebar-text hover:bg-sidebar-hover transition-colors"
        >
          <LayoutDashboard className="h-4 w-4" />
          Dashboards
        </Link>
        <button
          onClick={() => openSettings(true)}
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-sidebar-text hover:bg-sidebar-hover transition-colors"
        >
          <Settings className="h-4 w-4" />
          Settings
        </button>
      </div>

      {/* Context menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          session={contextMenu.session}
          onRename={handleRenameStart}
          onDelete={handleDelete}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}
