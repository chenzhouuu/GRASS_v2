"""Domain-aware dashboard card templates for supply-chain graphs."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DomainCardTemplate:
    id: str
    title: str
    description: str
    aliases: tuple[str, ...]
    cypher: str
    type: str = "kpi"
    exact: bool = True
    priority: int = 10
    unit: str | None = None
    value_format: str | None = None
    size: str = "small"
    timeout_ms: int = 15000
    max_rows: int = 500
    display: dict[str, Any] | None = None
    drilldown_template: str | None = None
    domain: str = "visibility"


DOMAIN_CARD_TEMPLATES: tuple[DomainCardTemplate, ...] = (
    DomainCardTemplate(
        id="domain-farms",
        title="Farms",
        description="Count of farm entities in the connected graph.",
        aliases=("Farm", "DairyFarm"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Farm', 'DairyFarm']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        drilldown_template=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Farm', 'DairyFarm']) "
            "RETURN n LIMIT 25"
        ),
    ),
    DomainCardTemplate(
        id="domain-processors",
        title="Processors",
        description="Count of processor or plant entities.",
        aliases=("Processor", "Plant"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Processor', 'Plant']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        drilldown_template=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Processor', 'Plant']) "
            "RETURN n LIMIT 25"
        ),
        priority=11,
    ),
    DomainCardTemplate(
        id="domain-cooperatives",
        title="Cooperatives",
        description="Count of cooperative entities.",
        aliases=("Cooperative", "Coop"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Cooperative', 'Coop']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        priority=12,
    ),
    DomainCardTemplate(
        id="pa-dairy-total-production",
        title="Annual Milk Production",
        description="Total represented farm production in pounds per year.",
        aliases=("DairyFarm",),
        cypher="MATCH (f:DairyFarm) RETURN sum(f.annual_production_lbs) AS value",
        unit="lbs/year",
        value_format="compact",
        priority=13,
        domain="production",
    ),
    DomainCardTemplate(
        id="pa-dairy-organic-farm-share",
        title="Organic Farm Share",
        description="Share of dairy farms marked organic certified.",
        aliases=("DairyFarm",),
        cypher=(
            "MATCH (f:DairyFarm) "
            "WITH count(f) AS total, "
            "count(CASE WHEN f.organic_certified = true THEN 1 END) AS organic "
            "RETURN CASE WHEN total = 0 THEN 0 ELSE toFloat(organic) / total END AS value"
        ),
        unit="percent",
        value_format="percent",
        priority=14,
        domain="organic",
    ),
    DomainCardTemplate(
        id="pa-dairy-cooperative-linkage",
        title="Cooperative Linkage",
        description="Share of farms connected to at least one cooperative.",
        aliases=("DairyFarm", "Cooperative"),
        cypher=(
            "MATCH (f:DairyFarm) "
            "OPTIONAL MATCH (f)-[:MEMBER_OF]->(c:Cooperative) "
            "WITH count(DISTINCT f) AS total, "
            "count(DISTINCT CASE WHEN c IS NOT NULL THEN f END) AS linked "
            "RETURN CASE WHEN total = 0 THEN 0 ELSE toFloat(linked) / total END AS value"
        ),
        unit="percent",
        value_format="percent",
        priority=15,
        domain="network",
    ),
    DomainCardTemplate(
        id="pa-dairy-organic-processors",
        title="Organic-Capable Processors",
        description="Processors that can handle organic dairy products.",
        aliases=("Processor",),
        cypher="MATCH (p:Processor) WHERE p.organic_capable = true RETURN count(p) AS value",
        unit="count",
        value_format="integer",
        priority=16,
        domain="organic",
    ),
    DomainCardTemplate(
        id="domain-retailers",
        title="Retailers",
        description="Retail demand nodes represented in the supply chain graph.",
        aliases=("Retailer", "Store", "Market"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Retailer', 'Store', 'Market']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        priority=17,
        domain="demand",
    ),
    DomainCardTemplate(
        id="domain-distribution-centers",
        title="Distribution Centers",
        description="Downstream logistics nodes available for finished dairy products.",
        aliases=("DistributionCenter", "Distribution_Center", "Warehouse"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN "
            "['DistributionCenter', 'Distribution_Center', 'Warehouse']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        priority=18,
        domain="logistics",
    ),
    DomainCardTemplate(
        id="domain-routes",
        title="Routes / Shipments",
        description="Count of route or shipment entities.",
        aliases=("Route", "Shipment"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['Route', 'Shipment']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        priority=19,
        domain="logistics",
    ),
    DomainCardTemplate(
        id="domain-risk-events",
        title="Risk Events",
        description="Modeled disruptions, hazard events, or other risks attached to the graph.",
        aliases=("RiskEvent", "Disruption", "Hazard"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN ['RiskEvent', 'Disruption', 'Hazard']) "
            "RETURN count(n) AS value"
        ),
        unit="count",
        value_format="integer",
        priority=20,
        domain="risk",
    ),
    DomainCardTemplate(
        id="pa-dairy-processor-headroom",
        title="Monthly Processor Headroom",
        description="Total unused monthly processing capacity represented in the graph.",
        aliases=("Processor",),
        cypher="MATCH (p:Processor) RETURN sum(p.capacity_headroom_lbs_month) AS value",
        unit="lbs/month",
        value_format="compact",
        priority=21,
        domain="capacity",
    ),
    DomainCardTemplate(
        id="domain-geo-coverage",
        title="Geo Coverage",
        description="Share of geo-capable entities with coordinates.",
        aliases=("Farm", "Facility", "Processor", "Plant"),
        cypher=(
            "MATCH (n) "
            "WHERE any(label IN labels(n) WHERE label IN "
            "['Farm', 'DairyFarm', 'Facility', 'Processor', 'Plant', "
            "'Cooperative', 'DistributionCenter', 'Retailer', 'StorageFacility']) "
            "WITH n, n.lat AS lat, n.lon AS lng "
            "WITH count(n) AS total, "
            "count(CASE WHEN "
            "lat IS NOT NULL AND lng IS NOT NULL "
            "THEN 1 END) AS withGeo "
            "RETURN CASE WHEN total = 0 THEN 0 ELSE toFloat(withGeo) / total END AS value"
        ),
        unit="percent",
        value_format="percent",
        priority=30,
        domain="data-quality",
    ),
    DomainCardTemplate(
        id="pa-dairy-farms-by-county",
        title="Farm Density by County",
        description="Top counties by represented dairy farm count.",
        aliases=("Farm", "DairyFarm", "County"),
        type="bar",
        cypher=(
            "MATCH (f:DairyFarm)-[:LOCATED_IN]->(c:County) "
            "RETURN c.name AS label, count(f) AS count "
            "ORDER BY count DESC LIMIT 12"
        ),
        exact=True,
        priority=40,
        size="medium",
        domain="geography",
    ),
    DomainCardTemplate(
        id="pa-dairy-processors-by-organic-capability",
        title="Processor Organic Capability",
        description="Split of processors by organic handling capability.",
        aliases=("Processor",),
        type="bar",
        cypher=(
            "MATCH (p:Processor) "
            "RETURN CASE WHEN p.organic_capable = true "
            "THEN 'Organic-capable' ELSE 'Conventional only' END AS label, "
            "count(p) AS count ORDER BY count DESC"
        ),
        exact=True,
        priority=41,
        size="medium",
        domain="organic",
    ),
    DomainCardTemplate(
        id="pa-dairy-processor-access",
        title="Processor Access Bands",
        description="Farm distribution by contracted processor access through cooperative links.",
        aliases=("Farm", "DairyFarm", "Processor", "Plant"),
        type="bar",
        cypher=(
            "MATCH (f:DairyFarm) "
            "OPTIONAL MATCH (f)-[:MEMBER_OF]->(:Cooperative)-[:SUPPLIES_RAW_MILK]->(p:Processor) "
            "WITH f, count(DISTINCT p) AS processorCount "
            "RETURN CASE "
            "WHEN processorCount = 0 THEN '0 contracted processors' "
            "WHEN processorCount <= 2 THEN '1-2 contracted processors' "
            "WHEN processorCount <= 5 THEN '3-5 contracted processors' "
            "ELSE '6+ contracted processors' END AS label, count(*) AS count "
            "ORDER BY count DESC"
        ),
        exact=True,
        priority=42,
        size="medium",
        timeout_ms=25000,
        domain="resilience",
    ),
    DomainCardTemplate(
        id="pa-dairy-processing-deserts",
        title="Processing Deserts",
        description="Counties with farms but no processor nodes in the same county field.",
        aliases=("Farm", "DairyFarm", "Processor", "Plant", "County"),
        type="table",
        cypher=(
            "MATCH (c:County)<-[:LOCATED_IN]-(f:DairyFarm) "
            "WITH c, count(f) AS farms "
            "OPTIONAL MATCH (c)<-[:LOCATED_IN]-(p:Processor) "
            "WITH c.name AS county, farms, count(p) AS processors "
            "WHERE processors = 0 "
            "RETURN county, farms, processors "
            "ORDER BY farms DESC LIMIT 15"
        ),
        exact=True,
        priority=50,
        size="wide",
        domain="infrastructure",
    ),
    DomainCardTemplate(
        id="pa-dairy-capacity-bottlenecks",
        title="Capacity Bottlenecks",
        description="Processors with the least monthly capacity headroom.",
        aliases=("Processor",),
        type="table",
        cypher=(
            "MATCH (p:Processor) "
            "RETURN p.name AS processor, p.county AS county, p.plant_type AS plant_type, "
            "p.organic_capable AS organic_capable, "
            "p.processing_capacity_lbs_day AS capacity_lbs_day, "
            "p.capacity_headroom_lbs_month AS headroom_lbs_month, "
            "p.utilization_ratio AS utilization_ratio "
            "ORDER BY headroom_lbs_month ASC LIMIT 12"
        ),
        exact=True,
        priority=51,
        size="wide",
        domain="capacity",
    ),
    DomainCardTemplate(
        id="pa-dairy-risk-exposure",
        title="Risk Exposure",
        description="Highest-severity risk events and affected entity counts.",
        aliases=("RiskEvent",),
        type="table",
        cypher=(
            "MATCH (e:RiskEvent)-[a:AFFECTS]->(n) "
            "RETURN e.name AS risk, e.event_type AS event_type, "
            "e.severity AS severity, e.probability AS probability, "
            "head(labels(n)) AS affected_type, count(n) AS affected_nodes, "
            "round(sum(a.impact_pct) * 100) / 100 AS total_impact_pct "
            "ORDER BY severity DESC, affected_nodes DESC LIMIT 12"
        ),
        exact=True,
        priority=52,
        size="wide",
        domain="risk",
    ),
    DomainCardTemplate(
        id="pa-dairy-facility-map",
        title="Facility Map",
        description="Geo-located farms, processors, cooperatives, distribution centers, and retailers.",
        aliases=("Farm", "DairyFarm", "Processor", "Plant", "Cooperative", "Retailer"),
        type="map",
        cypher=(
            "MATCH (n) "
            "WHERE n:DairyFarm OR n:Processor OR n:Cooperative OR "
            "n:DistributionCenter OR n:Retailer OR n:StorageFacility "
            "WITH n, n.lat AS lat, n.lon AS lng "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL "
            "RETURN elementId(n) AS id, coalesce(n.name, elementId(n)) AS name, "
            "CASE "
            "WHEN n:DairyFarm THEN 'Farm' "
            "WHEN n:Processor THEN 'Processor' "
            "WHEN n:Cooperative THEN 'Cooperative' "
            "WHEN n:DistributionCenter THEN 'Distribution Center' "
            "WHEN n:Retailer THEN 'Retailer' "
            "WHEN n:StorageFacility THEN 'Storage Facility' "
            "ELSE 'Facility' END AS type, "
            "toFloat(lat) AS lat, toFloat(lng) AS lng, "
            "coalesce(n.county, n.hq_county, '') AS county "
            "LIMIT 5000"
        ),
        exact=False,
        priority=60,
        size="large",
        max_rows=5000,
        display={"center": [40.9, -77.7], "zoom": 6},
        domain="geography",
    ),
    DomainCardTemplate(
        id="pa-dairy-supply-network",
        title="Supply Network",
        description="Stage-level PA dairy graph topology from farms through demand.",
        aliases=("Farm", "DairyFarm", "Processor", "Plant", "Cooperative", "Retailer"),
        type="network",
        cypher=(
            "CALL () { "
            "MATCH (:DairyFarm)-[r:MEMBER_OF]->(:Cooperative) "
            "RETURN 'Dairy Farms' AS source, 'Cooperatives' AS target, type(r) AS relationship, count(r) AS weight "
            "UNION ALL MATCH (:Cooperative)-[r:SUPPLIES_RAW_MILK]->(:Processor) "
            "RETURN 'Cooperatives' AS source, 'Processors' AS target, type(r) AS relationship, count(r) AS weight "
            "UNION ALL MATCH (:Processor)-[r:PRODUCES]->(:DairyProduct) "
            "RETURN 'Processors' AS source, 'Products' AS target, type(r) AS relationship, count(r) AS weight "
            "UNION ALL MATCH (:Processor)-[r:SHIPS_TO]->(:DistributionCenter) "
            "RETURN 'Processors' AS source, 'Distribution Centers' AS target, type(r) AS relationship, count(r) AS weight "
            "UNION ALL MATCH (:DistributionCenter)-[r:DELIVERS_TO]->(:Retailer) "
            "RETURN 'Distribution Centers' AS source, 'Retailers' AS target, type(r) AS relationship, count(r) AS weight "
            "UNION ALL MATCH (:Retailer)-[r:DEMANDS]->(:DairyProduct) "
            "RETURN 'Products' AS source, 'Retailers' AS target, type(r) AS relationship, count(r) AS weight "
            "} "
            "RETURN source, source AS sourceName, source AS sourceType, "
            "target, target AS targetName, target AS targetType, relationship, weight "
            "ORDER BY weight DESC"
        ),
        exact=True,
        priority=70,
        size="large",
        timeout_ms=25000,
        domain="network",
    ),
    DomainCardTemplate(
        id="pa-dairy-flow-sankey",
        title="Supply Flow Stages",
        description="Aggregated stage-to-stage relationship flow across the dairy supply chain.",
        aliases=("Farm", "DairyFarm", "Processor", "Plant", "Cooperative", "Retailer"),
        type="sankey",
        cypher=(
            "CALL () { "
            "MATCH (:DairyFarm)-[r:MEMBER_OF]->(:Cooperative) "
            "RETURN 'Dairy Farms' AS sourceStage, 'Cooperatives' AS targetStage, type(r) AS relationship, count(r) AS count "
            "UNION ALL MATCH (:Cooperative)-[r:SUPPLIES_RAW_MILK]->(:Processor) "
            "RETURN 'Cooperatives' AS sourceStage, 'Processors' AS targetStage, type(r) AS relationship, count(r) AS count "
            "UNION ALL MATCH (:Processor)-[r:PRODUCES]->(:DairyProduct) "
            "RETURN 'Processors' AS sourceStage, 'Products' AS targetStage, type(r) AS relationship, count(r) AS count "
            "UNION ALL MATCH (:Processor)-[r:SHIPS_TO]->(:DistributionCenter) "
            "RETURN 'Processors' AS sourceStage, 'Distribution Centers' AS targetStage, type(r) AS relationship, count(r) AS count "
            "UNION ALL MATCH (:DistributionCenter)-[r:DELIVERS_TO]->(:Retailer) "
            "RETURN 'Distribution Centers' AS sourceStage, 'Retailers' AS targetStage, type(r) AS relationship, count(r) AS count "
            "UNION ALL MATCH (:Retailer)-[r:DEMANDS]->(:DairyProduct) "
            "RETURN 'Products' AS sourceStage, 'Retailers' AS targetStage, type(r) AS relationship, count(r) AS count "
            "} "
            "RETURN sourceStage, targetStage, relationship, count "
            "ORDER BY count DESC"
        ),
        exact=True,
        priority=80,
        size="wide",
        timeout_ms=25000,
        domain="flow",
    ),
    DomainCardTemplate(
        id="domain-orphan-nodes",
        title="Orphan Nodes",
        description="Nodes with no relationships.",
        aliases=("Farm", "Processor", "Supplier", "Route"),
        cypher="MATCH (n) WHERE NOT (n)--() RETURN count(n) AS value",
        type="quality",
        priority=30,
        unit="count",
        value_format="integer",
        domain="data-quality",
    ),
)


def _normalize(label: str) -> str:
    return label.strip().lower()


def match_domain_cards(detected_labels: list[str]) -> list[DomainCardTemplate]:
    normalized = {_normalize(label) for label in detected_labels}
    matched: list[DomainCardTemplate] = []
    for template in DOMAIN_CARD_TEMPLATES:
        if any(_normalize(alias) in normalized for alias in template.aliases):
            matched.append(template)
    return matched
