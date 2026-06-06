"""Data summarizer for the Analytics Agent — LIDA-inspired.

Computes per-column statistics from Cypher query results to give the LLM
a rich understanding of the data shape, types, ranges, and cardinality
WITHOUT sending all raw rows.

Design adapted from Microsoft LIDA's Summarizer:
  github.com/microsoft/lida/blob/main/lida/components/summarizer.py

Key differences from LIDA:
- Input is list[dict] (Cypher results) not a DataFrame
- No LLM enrichment step (semantic types derived from column names)
- Optimized for supply chain domain (lat/lon detection, entity names)
"""

import json
import logging
import math
import random
from typing import Any

logger = logging.getLogger(__name__)


def make_data_preview(records: list[dict], max_rows: int = 5) -> str:
    """Build a concise JSON preview of the first N rows.

    Shared utility used by Analytics, Optimization, and Report agents.
    """
    if not records:
        return "(no data available)"
    text = json.dumps(records[:max_rows], indent=2, default=str)
    if len(records) > max_rows:
        text += f"\n... ({len(records)} rows total)"
    return text


def _safe_float(value: Any) -> float | None:
    """Convert to float, returning None for non-numeric / null values."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def _detect_dtype(values: list[Any]) -> str:
    """Detect the data type of a column from sample values.

    Returns one of: 'number', 'boolean', 'date', 'category', 'string'.
    Adapted from LIDA's Summarizer.get_column_properties() dtype detection.
    """
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "string"

    # Check boolean
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"

    # Check numeric
    numeric_count = sum(1 for v in non_null if _safe_float(v) is not None)
    if numeric_count / len(non_null) > 0.8:
        return "number"

    # Check if all values look like dates (contains - or / and digits)
    str_values = [str(v) for v in non_null[:20]]
    date_patterns = sum(
        1 for s in str_values
        if any(c in s for c in ("-", "/")) and any(c.isdigit() for c in s) and len(s) >= 8
    )
    if date_patterns / len(str_values) > 0.8:
        return "date"

    # Category vs string: low cardinality = category
    unique_ratio = len(set(str(v) for v in non_null)) / len(non_null) if non_null else 1.0
    if unique_ratio < 0.5:
        return "category"

    return "string"


# Property semantics from the Neo4j schema — units and meaning.
# These annotations help the Optimization/Analytics agents understand
# column semantics without guessing (e.g., "transport_cost" is a monthly
# total, NOT a per-unit rate).
PROPERTY_SEMANTICS: dict[str, str] = {
    "transport_cost": "Total monthly transport cost for this route in USD (NOT per-unit — do NOT multiply by volume)",
    "volume_lbs_month": "Monthly shipping volume in pounds",
    "distance_miles": "One-way distance in miles",
    "production_cost_per_unit": "Cost per unit produced (USD/unit)",
    "processing_capacity_lbs_day": "Daily processing capacity in pounds",
    "annual_production_lbs": "Annual milk production in pounds",
    "monthly_production_gal": "Monthly milk production in gallons",
    "herd_size": "Number of dairy cows",
    "cold_storage_capacity_sqft": "Cold storage area in square feet",
    "weekly_dairy_demand_gal": "Weekly dairy demand in gallons",
    "volume_units_month": "Monthly production volume in units",
    "volume_units_week": "Weekly delivery volume in units",
    "last_mile_cost": "Last-mile delivery cost in USD",
    "hauling_contribution_per_cwt": "Hauling cost per hundredweight (cwt) in USD",
    "price_per_cwt": "Price per hundredweight in USD",
    "transit_time_hrs": "Transit time in hours",
    "blend_price_per_cwt": "FMMO blend price per hundredweight in USD",
    "avg_retail_price_per_unit": "Average retail price per unit in USD",
    "cost": "Total cost in USD (NOT per-unit unless column name includes 'per')",
    "volume": "Volume quantity (check units from column name suffix)",
}


def _get_property_semantics(column_name: str) -> str | None:
    """Look up semantic annotation for a column name."""
    name_lower = column_name.lower()
    # Exact match
    if name_lower in PROPERTY_SEMANTICS:
        return PROPERTY_SEMANTICS[name_lower]
    # Check if column name ends with a known property (e.g., "s.transport_cost")
    for prop, desc in PROPERTY_SEMANTICS.items():
        if name_lower.endswith(prop):
            return desc
    return None


def _infer_semantic_type(column_name: str, dtype: str) -> str:
    """Infer semantic type from column name (no LLM needed).

    LIDA uses an LLM call for this; we use heuristic matching for speed.
    """
    name_lower = column_name.lower()

    # Geographic
    if name_lower in ("lat", "latitude"):
        return "latitude"
    if name_lower in ("lon", "lng", "longitude"):
        return "longitude"
    if "county" in name_lower or "state" in name_lower or "region" in name_lower:
        return "geographic_region"
    if "zip" in name_lower or "fips" in name_lower:
        return "geographic_code"

    # Entity identifiers
    if name_lower.endswith("_id") or name_lower == "id":
        return "identifier"
    if "name" in name_lower:
        return "entity_name"

    # Quantities
    if any(kw in name_lower for kw in ("cost", "price", "revenue", "budget")):
        return "currency"
    if any(kw in name_lower for kw in ("count", "total", "num", "quantity")):
        return "count"
    if any(kw in name_lower for kw in ("volume", "capacity", "production", "lbs", "gallons")):
        return "volume"
    if any(kw in name_lower for kw in ("size", "area", "distance", "miles")):
        return "measurement"
    if any(kw in name_lower for kw in ("rate", "percent", "ratio", "yield")):
        return "rate"

    # Temporal
    if any(kw in name_lower for kw in ("date", "time", "month", "year", "day")):
        return "temporal"

    # Boolean
    if any(kw in name_lower for kw in ("is_", "has_", "organic", "certified", "active")):
        return "boolean_flag"

    return dtype  # fallback to dtype


def summarize_data(records: list[dict], n_samples: int = 3) -> dict:
    """Compute per-column statistics from Cypher query results.

    Returns a dict with the same structure as LIDA's Summary:
    {
        "dataset_description": str,
        "total_rows": int,
        "fields": [
            {
                "column": str,
                "properties": {
                    "dtype": "number"|"category"|"string"|"boolean"|"date",
                    "semantic_type": str,
                    "num_unique_values": int,
                    "samples": list,
                    "min": numeric (if number),
                    "max": numeric (if number),
                    "mean": numeric (if number),
                    "std": numeric (if number),
                }
            }
        ],
        "field_names": list[str]
    }
    """
    if not records:
        return {
            "dataset_description": "Empty dataset",
            "total_rows": 0,
            "fields": [],
            "field_names": [],
        }

    columns = list(records[0].keys())
    fields = []

    for col in columns:
        values = [r.get(col) for r in records]
        non_null = [v for v in values if v is not None]

        dtype = _detect_dtype(values)
        semantic_type = _infer_semantic_type(col, dtype)

        props: dict[str, Any] = {
            "dtype": dtype,
            "semantic_type": semantic_type,
            "num_unique_values": len(set(str(v) for v in non_null)) if non_null else 0,
        }

        # Add property semantics annotation if available
        sem = _get_property_semantics(col)
        if sem:
            props["description"] = sem

        # Numeric stats (adapted from LIDA)
        if dtype == "number":
            nums = [_safe_float(v) for v in non_null]
            nums = [n for n in nums if n is not None]
            if nums:
                props["min"] = min(nums)
                props["max"] = max(nums)
                props["mean"] = round(sum(nums) / len(nums), 2)
                if len(nums) > 1:
                    mean = props["mean"]
                    variance = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)
                    props["std"] = round(math.sqrt(variance), 2)

        # Samples: random n_samples from unique non-null values
        if non_null:
            unique_vals = list(set(str(v) for v in non_null))
            sample_count = min(n_samples, len(unique_vals))
            rng = random.Random(42)
            samples = rng.sample(unique_vals, sample_count)
            # Try to preserve original types for numeric samples
            if dtype == "number":
                typed_samples = []
                for s in samples:
                    f = _safe_float(s)
                    typed_samples.append(f if f is not None else s)
                props["samples"] = typed_samples
            else:
                props["samples"] = samples
        else:
            props["samples"] = []

        fields.append({"column": col, "properties": props})

    return {
        "dataset_description": f"Query results with {len(records)} rows and {len(columns)} columns",
        "total_rows": len(records),
        "fields": fields,
        "field_names": columns,
    }


def format_summary_for_prompt(summary: dict) -> str:
    """Format the data summary as a readable string for the LLM prompt.

    This replaces the raw JSON preview with a structured, informative summary
    that helps the LLM make better chart type and analysis decisions.
    """
    if not summary.get("fields"):
        return "(no data available)"

    lines = [
        f"Dataset: {summary['total_rows']} rows, {len(summary['field_names'])} columns",
        f"Columns: {', '.join(summary['field_names'])}",
        "",
        "Column details:",
    ]

    for field in summary["fields"]:
        col = field["column"]
        p = field["properties"]
        dtype = p["dtype"]
        sem = p["semantic_type"]
        nunique = p["num_unique_values"]
        samples = p.get("samples", [])

        parts = [f"  - {col} ({dtype}, {sem})"]
        parts.append(f"unique={nunique}")

        if dtype == "number":
            if "min" in p and "max" in p:
                parts.append(f"range=[{p['min']}, {p['max']}]")
            if "mean" in p:
                parts.append(f"mean={p['mean']}")
            if "std" in p:
                parts.append(f"std={p['std']}")
        if samples:
            sample_str = ", ".join(str(s) for s in samples[:3])
            parts.append(f"samples=[{sample_str}]")

        # Include semantic description if available (helps LLM understand units)
        desc = p.get("description")
        if desc:
            parts.append(f"NOTE: {desc}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)
