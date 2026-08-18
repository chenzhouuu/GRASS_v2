"""Per-session named-table workspace (Scenario Engine v2, P2-a).

Each retrieval step's result set is registered as a named table: one JSON
file under ``data/outputs/<session>/tables/`` plus an entry in that
directory's ``manifest.json``. Downstream agents render the catalog into
their prompts, and generated code loads any table with ``pd.read_json``.

This replaces "the latest query overwrites cypher_results.json" as the way
the Analytics Agent sees data: in a multi-step plan it can now join or
compare tables produced by *earlier* steps, not just the last one.
Concept adapted from TaskWeaver's stateful analytic session, disk-backed
to fit GRASS's subprocess execution model (no persistent kernel).

Tables are append-only for the lifetime of a session and never reset
between turns, mirroring the durable ``all_query_results`` state field.
"""

import json
import logging
import os
from typing import Optional

from .python_executor import PROJECT_ROOT, sanitize_session_id

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 3
MAX_PREVIEW_CHARS = 400


class SessionWorkspace:
    """Named-table registry for one session.

    All paths handed to agents/prompts are project-root-relative, matching
    the working directory of generated code (see ``execute_python``).
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._dir_rel = f"data/outputs/{sanitize_session_id(session_id)}/tables"

    @property
    def _dir_abs(self) -> str:
        return os.path.join(PROJECT_ROOT, self._dir_rel)

    @property
    def _manifest_abs(self) -> str:
        return os.path.join(self._dir_abs, "manifest.json")

    def catalog(self) -> list[dict]:
        """All registered tables, oldest first.

        The manifest lives inside the session directory, which is mounted
        read-write into the execution sandbox — sandboxed code can rewrite
        it, so its contents are untrusted. Entries whose path resolves
        outside this session's tables directory are dropped here, the
        single point where manifest data enters host-side code: otherwise
        ``gather_tagged_rows`` would open attacker-chosen files on the
        host and feed them into prompts.
        """
        try:
            with open(self._manifest_abs, encoding="utf-8") as f:
                entries = json.load(f)
        except FileNotFoundError:
            return []
        except ValueError:
            logger.warning("Corrupt workspace manifest at %s; starting fresh",
                           self._manifest_abs)
            return []

        safe_root = os.path.realpath(self._dir_abs) + os.sep
        kept: list[dict] = []
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            abs_path = os.path.realpath(
                os.path.join(PROJECT_ROOT, str(e.get("path", "")))
            )
            if abs_path.startswith(safe_root):
                kept.append(e)
            else:
                logger.warning(
                    "Rejecting out-of-workspace table path %r", e.get("path")
                )
        return kept

    def register_table(
        self, rows: list[dict], description: str, source: str = "cypher"
    ) -> dict:
        """Write *rows* as the next numbered table and record it in the manifest.

        Returns the manifest entry: name, path (project-root-relative),
        rows, columns, description, source, preview.
        """
        entries = self.catalog()
        name = f"t{len(entries) + 1}"
        rel_path = f"{self._dir_rel}/{name}.json"
        os.makedirs(self._dir_abs, exist_ok=True)
        with open(os.path.join(PROJECT_ROOT, rel_path), "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=str)

        entry = {
            "name": name,
            "path": rel_path,
            "rows": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "description": description,
            "source": source,
            "preview": json.loads(json.dumps(rows[:PREVIEW_ROWS], default=str)),
        }
        entries.append(entry)
        with open(self._manifest_abs, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return entry


def get_workspace(session_id: Optional[str]) -> Optional[SessionWorkspace]:
    """Workspace for the session, or None when no session id is available
    (benchmarks and tests, which keep the legacy single-file data flow)."""
    return SessionWorkspace(session_id) if session_id else None


def gather_tagged_rows(entries: list[dict]) -> list[dict]:
    """Flatten every table into one row list, each row tagged with its
    originating step (``_query_step`` = table description) — the shape the
    Optimization Agent previously received from ``all_query_results``."""
    rows: list[dict] = []
    for entry in entries:
        try:
            with open(os.path.join(PROJECT_ROOT, entry["path"]), encoding="utf-8") as f:
                table_rows = json.load(f)
        except (FileNotFoundError, ValueError):
            logger.warning("Workspace table %s unreadable; skipping", entry.get("path"))
            continue
        rows.extend({**row, "_query_step": entry["description"]} for row in table_rows)
    return rows


def format_catalog_for_prompt(entries: list[dict]) -> str:
    """Render the table catalog as a prompt block."""
    if not entries:
        return "(no tables registered yet)"
    blocks = []
    for e in entries:
        sample = json.dumps(e.get("preview", []), default=str)
        if len(sample) > MAX_PREVIEW_CHARS:
            sample = sample[:MAX_PREVIEW_CHARS] + "…"
        blocks.append(
            f"- {e['name']} ({e['rows']} rows) — {e['description']}\n"
            f"  path: {e['path']}\n"
            f"  columns: {', '.join(e['columns'])}\n"
            f"  sample: {sample}"
        )
    return "\n".join(blocks)
