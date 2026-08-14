"""Layer-1 structural scenario tools: graph-overlay disruption analysis.

A structural scenario is a set of ``GraphEdit``s (P1: node removals).
Nothing is ever written to Neo4j — removed entities are excluded from read
queries via parameterized ``NOT x.name IN $removed_<Label>`` predicates, so
every tool here is a deterministic read-only computation through the Cypher
gateway, with no LLM in the hot path and no optimization baseline required.

Tools:
- ``structural_impact``  — per-echelon connectivity before vs after the
  removal (an entity is *connected* when it has a surviving chain path to
  both the supply end and the market end of the flow chain).
- ``cascade_trace``      — hop-ordered affected frontier around the removed
  entities, upstream and downstream.
- ``nearest_alternatives`` — for each direct partner of a removed entity,
  the k nearest surviving entities of the removed label by geographic
  distance.

The flow chain (echelon labels + connecting relationships) is declarative:
``config/flow_chain.yaml``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..core.schemas import GraphEdit
from .cypher_gateway import get_cypher_gateway

logger = logging.getLogger(__name__)

FLOW_CHAIN_PATH = Path(__file__).resolve().parents[2] / "config" / "flow_chain.yaml"

MAX_DISCONNECTED_LIST = 500  # cap on per-echelon disconnected-name lists
MAX_TRACE_ENTITIES = 100     # cap on per-hop cascade entity lists
MAX_PARTNERS = 200           # cap on partners in nearest_alternatives


@dataclass(frozen=True)
class FlowChain:
    """Ordered supply-chain flow chain: echelons[i] -[rels[i]]-> echelons[i+1].

    Entity identity is the per-echelon ``id_properties`` entry; ``name`` is
    display-only (names are duplicated in this graph).
    """

    echelons: tuple[str, ...]
    rels: tuple[str, ...]
    id_properties: tuple[str, ...]  # aligned with echelons
    name_property: str = "name"

    def index_of(self, label: str) -> int:
        return self.echelons.index(label)

    def id_prop(self, label: str) -> str:
        return self.id_properties[self.index_of(label)]


@lru_cache(maxsize=1)
def load_flow_chain(path: str | None = None) -> FlowChain:
    raw = yaml.safe_load(Path(path or FLOW_CHAIN_PATH).read_text())
    echelons = tuple(raw["echelons"])
    chain = FlowChain(
        echelons=echelons,
        rels=tuple(raw["rels"]),
        id_properties=tuple(raw["id_properties"][label] for label in echelons),
        name_property=raw.get("name_property", "name"),
    )
    if len(chain.rels) != len(chain.echelons) - 1:
        raise ValueError(
            f"flow_chain.yaml: {len(chain.echelons)} echelons need "
            f"{len(chain.echelons) - 1} rels, got {len(chain.rels)}"
        )
    return chain


# ── query building ────────────────────────────────────────────────────


def resolve_edit_id(gateway: Any, chain: FlowChain, edit: GraphEdit) -> str:
    """Resolve one edit to its unique entity id (well-posedness gate).

    An explicit ``id`` passes through; a ``name`` is looked up and must match
    exactly one node — zero matches or a duplicated name raise with the
    candidate ids so the caller (or user) can disambiguate. Silently removing
    every homonym would corrupt the impact numbers.
    """
    if edit.id:
        return edit.id
    idp = chain.id_prop(edit.label)
    query = (
        f"MATCH (n:{edit.label})\n"
        f"WHERE n.{chain.name_property} = $name\n"
        f"RETURN n.{idp} AS id"
    )
    rows = _run_all(gateway, query, {"name": edit.name})
    ids = [r["id"] for r in rows if r.get("id")]
    if not ids:
        raise ValueError(f"No {edit.label} named '{edit.name}' exists in the graph")
    if len(ids) > 1:
        raise ValueError(
            f"{len(ids)} {edit.label} nodes share the name '{edit.name}' "
            f"(ids: {', '.join(sorted(ids))}); specify the id explicitly"
        )
    return ids[0]


def removal_params(
    chain: FlowChain, edits: list[GraphEdit], gateway: Any = None
) -> dict[str, list[str]]:
    """Map every chain label to its removed-id list (empty when untouched).

    Every label always gets a parameter so the query text is independent of
    the edit set. Raises on labels outside the chain — the tools cannot
    reason about entities that are not on the flow path.
    """
    gateway = gateway or get_cypher_gateway()
    params: dict[str, list[str]] = {f"removed_{label}": [] for label in chain.echelons}
    for edit in edits:
        if edit.op != "remove_node":
            continue
        key = f"removed_{edit.label}"
        if key not in params:
            raise ValueError(
                f"GraphEdit label '{edit.label}' is not on the flow chain "
                f"{list(chain.echelons)}"
            )
        params[key].append(resolve_edit_id(gateway, chain, edit))
    return params


def _segment(chain: FlowChain, lo: int, hi: int, var: str, anchor: str) -> tuple[str, list[str]]:
    """Build a chain path pattern from echelon ``lo`` to ``hi``.

    ``anchor`` names the already-bound variable at one end: "last" anchors
    ``(... )->(anchor_var)`` with fresh vars upstream; "first" anchors
    ``(anchor_var)-> ...`` with fresh vars downstream. Returns the pattern
    and the exclusion predicates for the fresh variables.
    """
    parts: list[str] = []
    wheres: list[str] = []
    for i in range(lo, hi + 1):
        label = chain.echelons[i]
        if (anchor == "last" and i == hi) or (anchor == "first" and i == lo):
            node = f"({var}:{label})"
        else:
            v = f"{var}{i}"
            node = f"({v}:{label})"
            wheres.append(f"NOT {v}.{chain.id_properties[i]} IN $removed_{label}")
        parts.append(node)
        if i < hi:
            parts.append(f"-[:{chain.rels[i]}]->")
    return "".join(parts), wheres


def connectivity_query(chain: FlowChain, echelon_idx: int) -> str:
    """Per-echelon connectivity aggregate under the current removal params.

    With all-empty removal params this measures the baseline; the same query
    with the scenario's params measures the counterfactual — the comparison
    is two parameter sets on one query.
    """
    e = echelon_idx
    label = chain.echelons[e]
    last = len(chain.echelons) - 1
    np = chain.name_property
    idp = chain.id_properties[e]

    if e == 0:
        supply = "true"
    else:
        pattern, wheres = _segment(chain, 0, e, var="n", anchor="last")
        supply = f"EXISTS {{ MATCH {pattern} WHERE {' AND '.join(wheres)} }}"

    if e == last:
        market = "true"
    else:
        pattern, wheres = _segment(chain, e, last, var="n", anchor="first")
        market = f"EXISTS {{ MATCH {pattern} WHERE {' AND '.join(wheres)} }}"

    return (
        f"MATCH (n:{label})\n"
        f"WHERE NOT n.{idp} IN $removed_{label}\n"
        f"WITH n, ({supply} AND {market}) AS connected\n"
        f"RETURN count(n) AS total,\n"
        f"       sum(CASE WHEN connected THEN 1 ELSE 0 END) AS connected_count,\n"
        f"       [x IN collect(CASE WHEN NOT connected THEN {{id: n.{idp}, name: n.{np}}} END) "
        f"WHERE x IS NOT NULL][0..{MAX_DISCONNECTED_LIST}] AS disconnected"
    )


def _run_all(gateway: Any, query: str, params: dict) -> list[dict]:
    result = gateway.read_cypher(query, params)
    if result.error:
        raise RuntimeError(f"graph_scenario query failed: {result.error}")
    return result.records or []


def _run(gateway: Any, query: str, params: dict) -> dict:
    rows = _run_all(gateway, query, params)
    return rows[0] if rows else {}


# ── tools ─────────────────────────────────────────────────────────────


def structural_impact(
    edits: list[GraphEdit], gateway: Any = None, chain: FlowChain | None = None
) -> dict[str, Any]:
    """Per-echelon connectivity delta: baseline vs with the edits applied."""
    gateway = gateway or get_cypher_gateway()
    chain = chain or load_flow_chain()
    scenario_params = removal_params(chain, edits, gateway)
    baseline_params = {k: [] for k in scenario_params}

    echelons: list[dict[str, Any]] = []
    for e, label in enumerate(chain.echelons):
        query = connectivity_query(chain, e)
        base = _run(gateway, query, baseline_params)
        scen = _run(gateway, query, scenario_params)
        base_disc = base.get("disconnected", [])
        scen_disc = scen.get("disconnected", [])
        base_ids = {d["id"] for d in base_disc}
        newly = sorted(
            (d for d in scen_disc if d["id"] not in base_ids),
            key=lambda d: d["id"],
        )
        # The exact impact number comes from the counts; the name list is
        # illustrative and may be truncated at MAX_DISCONNECTED_LIST. At the
        # removed entities' own echelon, connected_drop includes the removed
        # entities themselves (they leave the population).
        truncated = (
            len(base_disc) >= MAX_DISCONNECTED_LIST
            or len(scen_disc) >= MAX_DISCONNECTED_LIST
        )
        echelons.append({
            "echelon": label,
            "removed": scenario_params[f"removed_{label}"],
            "baseline_total": base.get("total", 0),
            "baseline_connected": base.get("connected_count", 0),
            "scenario_total": scen.get("total", 0),
            "scenario_connected": scen.get("connected_count", 0),
            "connected_drop": base.get("connected_count", 0) - scen.get("connected_count", 0),
            "newly_disconnected": newly,
            "newly_disconnected_truncated": truncated,
        })
    return {"edits": [ed.model_dump() for ed in edits], "echelons": echelons}


def cascade_trace(
    edits: list[GraphEdit],
    gateway: Any = None,
    chain: FlowChain | None = None,
) -> dict[str, Any]:
    """Hop-ordered affected frontier around the removed entities.

    Hop h upstream = entities at echelon r-h with a chain path into a
    removed entity; hop h downstream = entities at echelon r+h fed by one.
    Co-removed intermediates are excluded so impact does not flow through
    entities that are themselves offline.
    """
    gateway = gateway or get_cypher_gateway()
    chain = chain or load_flow_chain()
    params = removal_params(chain, edits, gateway)
    np = chain.name_property
    frontier: list[dict[str, Any]] = []

    removed_labels = sorted({e.label for e in edits if e.op == "remove_node"})
    for label in removed_labels:
        r = chain.index_of(label)
        idp = chain.id_prop(label)
        targets = params[f"removed_{label}"]
        for h in range(1, len(chain.echelons)):
            for direction, other in (("upstream", r - h), ("downstream", r + h)):
                if not 0 <= other < len(chain.echelons):
                    continue
                lo, hi = min(other, r), max(other, r)
                # Anchor the removed entity, fresh vars toward the frontier.
                anchor = "last" if direction == "upstream" else "first"
                pattern, wheres = _segment(chain, lo, hi, var="rm", anchor=anchor)
                x = f"rm{other}"
                x_id = chain.id_properties[other]
                query = (
                    f"MATCH {pattern}\n"
                    f"WHERE rm.{idp} IN $targets AND {' AND '.join(wheres)}\n"
                    f"RETURN count(DISTINCT {x}) AS count,\n"
                    f"       collect(DISTINCT {{id: {x}.{x_id}, name: {x}.{np}}})"
                    f"[0..{MAX_TRACE_ENTITIES}] AS entities"
                )
                row = _run(gateway, query, {**params, "targets": targets})
                if row.get("count", 0):
                    frontier.append({
                        "removed_label": label,
                        "hop": h,
                        "direction": direction,
                        "echelon": chain.echelons[other],
                        "count": row["count"],
                        "entities": row.get("entities", []),
                    })
    frontier.sort(key=lambda f: (f["hop"], f["direction"]))
    return {"edits": [ed.model_dump() for ed in edits], "frontier": frontier}


def nearest_alternatives(
    edits: list[GraphEdit],
    gateway: Any = None,
    chain: FlowChain | None = None,
    k: int = 3,
) -> dict[str, Any]:
    """For each direct partner of a removed entity, the k nearest surviving
    entities of the removed label by geographic distance (stored POINTs).

    Partners are the upstream feeders of the removed entity (who lose their
    outlet); for a removal at the first echelon, the downstream receivers
    (who lose supply).
    """
    gateway = gateway or get_cypher_gateway()
    chain = chain or load_flow_chain()
    params = removal_params(chain, edits, gateway)
    np = chain.name_property
    results: list[dict[str, Any]] = []

    removed_labels = sorted({e.label for e in edits if e.op == "remove_node"})
    for label in removed_labels:
        r = chain.index_of(label)
        idp = chain.id_prop(label)
        targets = params[f"removed_{label}"]
        if r > 0:
            partner_label = chain.echelons[r - 1]
            partner_pattern = f"(p:{partner_label})-[:{chain.rels[r - 1]}]->(rm:{label})"
        else:
            partner_label = chain.echelons[1]
            partner_pattern = f"(rm:{label})-[:{chain.rels[0]}]->(p:{partner_label})"
        partner_idp = chain.id_prop(partner_label)
        query = (
            f"MATCH {partner_pattern}\n"
            f"WHERE rm.{idp} IN $targets"
            f" AND NOT p.{partner_idp} IN $removed_{partner_label}\n"
            f"  AND p.location IS NOT NULL\n"
            f"WITH DISTINCT p LIMIT {MAX_PARTNERS}\n"
            f"MATCH (alt:{label})\n"
            f"WHERE NOT alt.{idp} IN $removed_{label} AND alt.location IS NOT NULL\n"
            f"WITH p, alt, point.distance(p.location, alt.location) / 1609.344 AS miles\n"
            f"ORDER BY miles ASC\n"
            f"WITH p, collect({{id: alt.{idp}, name: alt.{np}, "
            f"distance_miles: round(miles, 1)}})[0..$k] AS alternatives\n"
            f"RETURN p.{partner_idp} AS partner_id, p.{np} AS partner, alternatives\n"
            f"ORDER BY partner"
        )
        rows = gateway.read_cypher(query, {**params, "targets": targets, "k": k})
        if rows.error:
            raise RuntimeError(f"graph_scenario query failed: {rows.error}")
        results.append({
            "removed_label": label,
            "partner_echelon": partner_label,
            "partners": rows.records,
        })
    return {"edits": [ed.model_dump() for ed in edits], "alternatives": results}


if __name__ == "__main__":
    # Manual verification CLI:
    #   python -m src.tools.graph_scenario --label Processor --name "<entity name>"
    import argparse
    import json

    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Layer-1 structural scenario check")
    parser.add_argument("--label", required=True)
    parser.add_argument("--name", action="append", default=[],
                        help="Entity name (repeatable; ambiguous names list candidate ids)")
    parser.add_argument("--id", action="append", default=[],
                        help="Entity id, e.g. P0022 (repeatable; skips name resolution)")
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if not args.name and not args.id:
        parser.error("provide at least one --name or --id")

    edits = [GraphEdit(label=args.label, name=n) for n in args.name] + [
        GraphEdit(label=args.label, id=i) for i in args.id
    ]
    out = {
        "structural_impact": structural_impact(edits),
        "cascade_trace": cascade_trace(edits),
        "nearest_alternatives": nearest_alternatives(edits, k=args.k),
    }
    print(json.dumps(out, indent=2, default=str))
