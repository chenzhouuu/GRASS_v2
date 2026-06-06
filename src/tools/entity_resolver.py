"""Entity resolution tool for the Cypher Agent.

Resolves fuzzy entity mentions from user queries to exact database values
using a three-tier strategy:
  1. Alias/synonym table (instant, deterministic)
  2. Neo4j full-text index with Lucene fuzzy search
  3. APOC string similarity as fallback

Usage:
    from src.tools.entity_resolver import resolve_entity, ensure_fulltext_index

    ensure_fulltext_index()  # call once at startup
    # Then give resolve_entity to the Cypher Agent as a tool
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from ..utils.neo4j_connection import get_session

logger = logging.getLogger(__name__)

# ── Full-text index ──────────────────────────────────────────────────

FULLTEXT_INDEX_NAME = "entityNames"
INDEXED_LABELS = [
    "County",
    "DairyFarm",
    "DairyProduct",
    "Processor",
    "Retailer",
    "Cooperative",
    "DistributionCenter",
    "StorageFacility",
    "FMMORegion",
    "RiskEvent",
]


def ensure_fulltext_index() -> None:
    """Create the full-text index on entity names if it doesn't exist."""
    label_expr = "|".join(INDEXED_LABELS)
    query = (
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX_NAME} IF NOT EXISTS "
        f"FOR (n:{label_expr}) ON EACH [n.name]"
    )
    try:
        with get_session() as session:
            session.run(query)
        logger.info("Full-text index '%s' ensured", FULLTEXT_INDEX_NAME)
    except Exception as exc:
        logger.warning("Failed to create full-text index: %s", exc)


# ── Alias / synonym table ───────────────────────────────────────────

# Maps lowercase alias → (label, exact DB value or list of values).
# For category terms, the value is a list of matching product names.
ALIASES: dict[str, tuple[str, str | list[str]]] = {
    # Cooperative abbreviations
    "dfa": ("Cooperative", "Dairy Farmers of America"),
    "dairy farmers of america": ("Cooperative", "Dairy Farmers of America"),
    "lol": ("Cooperative", "Land O'Lakes"),
    "land o lakes": ("Cooperative", "Land O'Lakes"),
    "land olakes": ("Cooperative", "Land O'Lakes"),
    "organic valley": ("Cooperative", "Organic Valley"),
    "agri-mark": ("Cooperative", "Agri-Mark"),
    "agrimark": ("Cooperative", "Agri-Mark"),
    # Product category terms
    "cheese": ("DairyProduct", [
        "Cheddar Cheese", "Colby Jack Cheese", "Cottage Cheese",
        "Cream Cheese", "Mozzarella Cheese", "Provolone Cheese",
        "Swiss Cheese",
    ]),
    "yogurt": ("DairyProduct", [
        "Greek Yogurt", "Regular Yogurt", "Frozen Yogurt",
    ]),
    "milk": ("DairyProduct", [
        "Whole Milk", "Skim Milk", "2% Reduced Fat Milk",
        "Chocolate Milk", "Organic Whole Milk",
    ]),
    "butter": ("DairyProduct", ["Butter", "Salted Butter"]),
    "cream": ("DairyProduct", ["Heavy Cream", "Sour Cream", "Ice Cream"]),
    "ice cream": ("DairyProduct", "Ice Cream"),
    "whole milk": ("DairyProduct", "Whole Milk"),
    "skim milk": ("DairyProduct", "Skim Milk"),
    "organic milk": ("DairyProduct", "Organic Whole Milk"),
    "reduced fat milk": ("DairyProduct", "2% Reduced Fat Milk"),
    "2% milk": ("DairyProduct", "2% Reduced Fat Milk"),
    "chocolate milk": ("DairyProduct", "Chocolate Milk"),
    # FMMO region aliases
    "northeast": ("FMMORegion", "Northeast"),
    "mideast": ("FMMORegion", "Mideast"),
    "mid-east": ("FMMORegion", "Mideast"),
}


def _check_alias(mention: str) -> dict | None:
    """Check the alias table for an exact match. Returns result dict or None."""
    key = mention.strip().lower()
    if key not in ALIASES:
        return None
    label, value = ALIASES[key]
    if isinstance(value, list):
        return {
            "match_type": "alias_category",
            "label": label,
            "candidates": [{"name": v, "score": 1.0} for v in value],
            "note": f"'{mention}' is a category term matching {len(value)} {label} entries.",
        }
    return {
        "match_type": "alias_exact",
        "label": label,
        "candidates": [{"name": value, "score": 1.0}],
    }


# ── Full-text search ────────────────────────────────────────────────

def _fulltext_search(mention: str, label: str | None, limit: int) -> list[dict]:
    """Query the full-text index with Lucene fuzzy syntax."""
    # Build Lucene query: add ~ for fuzzy on each word
    words = mention.strip().split()
    lucene_parts = [f"{w}~" for w in words if w]
    lucene_query = " ".join(lucene_parts)

    cypher = (
        f'CALL db.index.fulltext.queryNodes("{FULLTEXT_INDEX_NAME}", $query) '
        "YIELD node, score "
    )
    if label:
        cypher += f'WHERE "{label}" IN labels(node) '
    cypher += "RETURN labels(node)[0] AS label, node.name AS name, score "
    cypher += f"ORDER BY score DESC LIMIT {limit}"

    try:
        with get_session() as session:
            result = session.run(cypher, parameters={"query": lucene_query})
            # Deduplicate by (label, name), keeping highest score
            seen: dict[tuple[str, str], dict] = {}
            for rec in result:
                key = (rec["label"], rec["name"])
                if key not in seen or rec["score"] > seen[key]["score"]:
                    seen[key] = dict(rec)
            return sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    except Exception as exc:
        logger.warning("Full-text search failed: %s", exc)
        return []


# ── APOC similarity fallback ────────────────────────────────────────

def _apoc_similarity_search(
    mention: str, label: str, limit: int
) -> list[dict]:
    """Fallback: scan nodes of a given label using APOC string similarity."""
    cypher = (
        f"MATCH (n:{label}) "
        "WITH n, apoc.text.jaroWinklerDistance(toLower(n.name), toLower($mention)) AS score "
        "WHERE score > 0.7 "
        "RETURN labels(n)[0] AS label, n.name AS name, score "
        f"ORDER BY score DESC LIMIT {limit}"
    )
    try:
        with get_session() as session:
            result = session.run(cypher, parameters={"mention": mention})
            return [dict(rec) for rec in result]
    except Exception as exc:
        logger.warning("APOC similarity search failed: %s", exc)
        return []


# ── Public tool ──────────────────────────────────────────────────────

@tool
def resolve_entity(
    mention: Annotated[str, "The entity name or phrase to resolve (e.g. 'Land O Lakes', 'Lancster', 'cheese')."],
    label: Annotated[str | None, "Optional node label to restrict search (e.g. 'County', 'DairyProduct'). If omitted, searches all labels."] = None,
) -> Annotated[dict, "Resolution result with 'candidates' list sorted by score."]:
    """Resolve a fuzzy entity mention to exact database values.

    Use this tool BEFORE writing a Cypher query when you are unsure whether
    an entity name from the user's question exactly matches a value in the
    database. For example:
      - User says "Land O Lakes" → resolves to Cooperative "Land O'Lakes"
      - User says "Lancster"     → resolves to County "Lancaster"
      - User says "cheese"       → resolves to all cheese DairyProduct names

    Returns a dict with:
      - candidates: list of {name, score, label} sorted by relevance
      - match_type: "alias_exact", "alias_category", "fulltext", "similarity", or "none"
    """
    mention = mention.strip()
    if not mention:
        return {"candidates": [], "match_type": "none", "error": "Empty mention"}

    # Tier 1: alias table
    alias_result = _check_alias(mention)
    if alias_result:
        logger.info("Entity '%s' resolved via alias table", mention)
        return alias_result

    # Tier 2: full-text index
    ft_results = _fulltext_search(mention, label, limit=5)
    if ft_results:
        logger.info(
            "Entity '%s' resolved via full-text index (%d candidates)",
            mention, len(ft_results),
        )
        return {
            "match_type": "fulltext",
            "candidates": ft_results,
        }

    # Tier 3: APOC similarity (only if label is specified, to avoid full scan)
    if label:
        sim_results = _apoc_similarity_search(mention, label, limit=5)
        if sim_results:
            logger.info(
                "Entity '%s' resolved via APOC similarity (%d candidates)",
                mention, len(sim_results),
            )
            return {
                "match_type": "similarity",
                "candidates": sim_results,
            }

    logger.info("Entity '%s' could not be resolved", mention)
    return {
        "match_type": "none",
        "candidates": [],
        "note": f"No match found for '{mention}'. The entity may not exist in the database.",
    }
