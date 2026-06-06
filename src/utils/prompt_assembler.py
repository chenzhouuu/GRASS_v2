"""Assemble the Supervisor's system prompt from layered components.

Each layer is loaded from a different source:
- Layers 1, 5: Static text files (src/prompts/supervisor_*.txt)
- Layer 2: Static text file (domain ontology)
- Layers 3, 4: Auto-generated from Neo4j introspection
"""

import logging
import os
import time

from .schema_loader import get_schema
from .neo4j_connection import get_session

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _load_prompt(filename: str) -> str:
    """Load a prompt text file from src/prompts/."""
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class PromptAssembler:
    """Assemble the Supervisor's system prompt from five layers.

    Layer 1: Identity & Role (static)
    Layer 2: Domain Ontology (semi-static)
    Layer 3: Live Schema (auto from Neo4j)
    Layer 4: Value Grounding (auto from Neo4j)
    Layer 5: Orchestration Protocol (static)
    """

    def __init__(self, schema_source: str = "auto"):
        self.schema_source = schema_source
        self._cache: dict[str, str] = {}
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 300  # 5 minutes

    def assemble(self) -> str:
        """Build the full system prompt from all five layers."""
        if self._is_cache_valid():
            return self._cache["full_prompt"]

        layers = [
            self._layer_1_identity(),
            self._layer_2_domain_ontology(),
            self._layer_3_live_schema(),
            self._layer_4_value_grounding(),
            self._layer_5_orchestration(),
        ]

        full_prompt = "\n\n".join(layers)
        self._cache["full_prompt"] = full_prompt
        self._cache_timestamp = time.time()
        logger.info("Supervisor prompt assembled (%d chars)", len(full_prompt))
        return full_prompt

    def _layer_1_identity(self) -> str:
        return _load_prompt("supervisor_identity.txt")

    def _layer_2_domain_ontology(self) -> str:
        return _load_prompt("supervisor_domain_ontology.txt")

    def _layer_3_live_schema(self) -> str:
        schema_text = get_schema(source=self.schema_source)
        return f"## Neo4j Schema\n\n{schema_text}"

    def _layer_4_value_grounding(self) -> str:
        """Auto-generate entity value lists from Neo4j."""
        try:
            return self._fetch_value_reference()
        except Exception as exc:
            logger.warning("Value grounding fetch failed: %s", exc)
            return "## Entity Value Reference\n\n(Not available — database query failed)"

    def _layer_5_orchestration(self) -> str:
        return _load_prompt("supervisor_orchestration.txt")

    def _fetch_value_reference(self) -> str:
        """Query Neo4j for entity names and categorical values."""
        with get_session() as session:
            counties = sorted([
                r["name"] for r in session.run(
                    "MATCH (c:County) RETURN c.name AS name"
                )
            ])
            products_by_class: dict[str, list[str]] = {}
            for r in session.run(
                "MATCH (dp:DairyProduct) "
                "RETURN dp.name AS name, dp.milk_class AS milk_class "
                "ORDER BY dp.milk_class, dp.name"
            ):
                cls = r["milk_class"]
                products_by_class.setdefault(cls, []).append(r["name"])
            coops = sorted([
                r["name"] for r in session.run(
                    "MATCH (c:Cooperative) RETURN c.name AS name"
                )
            ])
            risk_types = sorted([
                r["type"] for r in session.run(
                    "MATCH (re:RiskEvent) "
                    "RETURN DISTINCT re.event_type AS type"
                )
            ])
            processor_types = sorted([
                r["type"] for r in session.run(
                    "MATCH (p:Processor) "
                    "RETURN DISTINCT p.plant_type AS type"
                )
            ])

        lines = ["## Entity Value Reference", ""]
        lines.append(f"**Counties** ({len(counties)} PA counties, title case):")
        lines.append(", ".join(counties))
        lines.append("")
        total_products = sum(len(v) for v in products_by_class.values())
        lines.append(f"**Dairy Products** ({total_products}, by milk class):")
        for cls in sorted(products_by_class.keys()):
            lines.append(f"  Class {cls}: {', '.join(products_by_class[cls])}")
        lines.append("")
        lines.append(f"**Cooperatives** ({len(coops)}):")
        lines.append(", ".join(coops))
        lines.append("")
        lines.append(f"**Processor Types**: {', '.join(processor_types)}")
        lines.append(f"**Risk Event Types**: {', '.join(risk_types)}")
        lines.append("**FMMO Regions**: Northeast (Order 1), Mideast (Order 33)")

        return "\n".join(lines)

    def _is_cache_valid(self) -> bool:
        return (
            "full_prompt" in self._cache
            and (time.time() - self._cache_timestamp) < self._cache_ttl
        )
