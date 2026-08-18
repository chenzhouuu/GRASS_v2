"""Build dashboard card catalogs from detected graph labels."""

import logging

from ..tools.cypher_gateway import get_cypher_gateway
from ..utils.neo4j_connection import get_neo4j_runtime_state
from .context import build_dashboard_context
from .domain_registry import match_domain_cards
from .models import (
    DashboardCardDefinition,
    DashboardCardDrilldown,
    DashboardCatalogResponse,
)

logger = logging.getLogger(__name__)
_catalog_cache: dict[str, DashboardCatalogResponse] = {}
PA_DAIRY_CORE_LABELS = {
    "DairyFarm",
    "Processor",
    "Cooperative",
    "DistributionCenter",
    "Retailer",
    "DairyProduct",
    "County",
}


def clear_dashboard_catalog_cache() -> None:
    """Clear cached dashboard catalogs after connection or test fixture changes."""
    _catalog_cache.clear()


def fetch_label_names() -> list[str]:
    try:
        result = get_cypher_gateway().read_cypher(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN DISTINCT label AS label ORDER BY label"
        )
    except Exception:
        logger.debug("Failed to fetch label names for dashboard catalog", exc_info=True)
        return []
    if result.error:
        return []
    return [str(row["label"]) for row in result.records if row.get("label")]


def _schema_cards() -> list[DashboardCardDefinition]:
    return [
        DashboardCardDefinition(
            id="schema-total-nodes",
            layer="schema",
            type="kpi",
            title="Total Nodes",
            description="Live count of all nodes.",
            cypher="MATCH (n) RETURN count(n) AS value",
            exact=True,
            priority=100,
        ),
        DashboardCardDefinition(
            id="schema-nodes-by-label",
            layer="schema",
            type="bar",
            title="Nodes by Label",
            description="Distribution of node labels.",
            cypher=(
                "MATCH (n) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS count ORDER BY count DESC"
            ),
            exact=True,
            priority=101,
        ),
    ]


def build_dashboard_catalog(
    *,
    fingerprint: str,
    labels: list[str],
) -> DashboardCatalogResponse:
    cards: list[DashboardCardDefinition] = []
    for template in match_domain_cards(labels):
        cards.append(
            DashboardCardDefinition(
                id=template.id,
                layer="operational",
                type=template.type,  # type: ignore[arg-type]
                title=template.title,
                description=template.description,
                cypher=template.cypher.strip(),
                exact=template.exact,
                priority=template.priority,
                unit=template.unit,
                valueFormat=template.value_format,
                size=template.size,  # type: ignore[arg-type]
                timeoutMs=template.timeout_ms,
                maxRows=template.max_rows,
                display=template.display or {},
                drilldown=DashboardCardDrilldown(
                    kind="cypher",
                    template=template.drilldown_template or template.cypher,
                ),
                domain=template.domain,
            )
        )
    has_operational = any(card.layer == "operational" for card in cards)
    if not has_operational:
        cards.extend(_schema_cards())
    label_set = set(labels)
    domain_profile = (
        "pa-dairy-supply-chain"
        if PA_DAIRY_CORE_LABELS.issubset(label_set)
        else "dairy-supply-chain" if has_operational else "generic"
    )
    return DashboardCatalogResponse(
        fingerprint=fingerprint,
        cards=sorted(cards, key=lambda card: card.priority),
        detectedLabels=labels,
        domainProfile=domain_profile,
    )


def build_catalog_for_runtime(*, force_refresh: bool = False) -> DashboardCatalogResponse:
    context = build_dashboard_context()
    if not context.connection.connected:
        return DashboardCatalogResponse(
            fingerprint=context.fingerprint,
            cards=_schema_cards(),
            detectedLabels=[],
            domainProfile="generic",
        )
    if not force_refresh and context.fingerprint in _catalog_cache:
        return _catalog_cache[context.fingerprint]
    labels = fetch_label_names()
    catalog = build_dashboard_catalog(fingerprint=context.fingerprint, labels=labels)
    _catalog_cache[context.fingerprint] = catalog
    return catalog
