"""Deterministic what-if perturbation transforms (no LLM).

Applies a list of ``Perturbation`` diffs to baseline data rows so the cached
baseline PuLP code can be re-run on the perturbed data. This is the fast,
provenance-clean path for numeric what-ifs (demand ±%, capacity changes,
entity removal). Structural perturbations (constraint/bound edits) are NOT
handled here — they are deferred to P3 and applied by editing the formulation.
"""

from __future__ import annotations

import logging

from ..core.schemas import Perturbation

logger = logging.getLogger(__name__)

# Kinds applied deterministically by this module.
DETERMINISTIC_KINDS = {"scale_param", "set_param", "scale_capacity", "remove_entity"}


def _matches(row: dict, selector: dict) -> bool:
    """True when the row matches every key/value in the selector (string-compared)."""
    return all(str(row.get(k)) == str(v) for k, v in selector.items())


def apply_perturbations(
    rows: list[dict], perturbations: list[Perturbation]
) -> tuple[list[dict], list[str]]:
    """Apply deterministic perturbations to a copy of ``rows``.

    Returns ``(perturbed_rows, provenance_log)``. The input ``rows`` are never
    mutated. ``structural`` perturbations are recorded in the log and skipped
    (handled upstream by the formulation editor in a later phase).
    """
    out: list[dict] = [dict(r) for r in rows]
    log: list[str] = []

    for p in perturbations:
        selector = p.selector or {}

        if p.kind == "remove_entity":
            before = len(out)
            out = [r for r in out if not _matches(r, selector)]
            log.append(f"remove_entity {selector or '{}'}: dropped {before - len(out)} rows")

        elif p.kind in ("scale_param", "scale_capacity"):
            if p.factor is None:
                log.append(f"{p.kind} '{p.target}': skipped (no factor)")
                continue
            n = 0
            for r in out:
                if _matches(r, selector) and isinstance(r.get(p.target), (int, float)):
                    r[p.target] = r[p.target] * p.factor
                    n += 1
            log.append(f"{p.kind} '{p.target}' ×{p.factor} on {n} rows {selector or ''}".rstrip())

        elif p.kind == "set_param":
            if p.value is None:
                log.append(f"set_param '{p.target}': skipped (no value)")
                continue
            n = 0
            for r in out:
                if _matches(r, selector) and p.target in r:
                    r[p.target] = p.value
                    n += 1
            log.append(f"set_param '{p.target}' = {p.value} on {n} rows {selector or ''}".rstrip())

        elif p.kind == "structural":
            log.append(f"structural perturbation deferred (P3): {p.instruction[:80]}")

        else:  # pragma: no cover - schema Literal prevents this
            log.append(f"unknown perturbation kind: {p.kind}")

    return out, log


__all__ = ["apply_perturbations", "DETERMINISTIC_KINDS"]
