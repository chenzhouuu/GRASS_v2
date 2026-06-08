"""Shared Plotly JSON marker protocol for GRASS.

Defines the PLOTLY_JSON::...::END_PLOTLY_JSON convention used to capture
Plotly chart specs from subprocess stdout. Used by both the Analytics Agent
(extraction) and the Supervisor Agent (sanitization).
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

PLOTLY_MARKER_START = "PLOTLY_JSON::"
PLOTLY_MARKER_END = "::END_PLOTLY_JSON"

PLOTLY_PATTERN = re.compile(
    re.escape(PLOTLY_MARKER_START) + r"(.*?)" + re.escape(PLOTLY_MARKER_END),
    re.DOTALL,
)


def extract_plotly_specs(text: str) -> list[dict]:
    """Extract Plotly JSON specs from text using delimiter markers."""
    specs = []
    for match in PLOTLY_PATTERN.finditer(text):
        raw = match.group(1).strip()
        try:
            spec = json.loads(raw)
            if isinstance(spec, dict):
                specs.append(spec)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Plotly JSON spec (%d chars)", len(raw))
    return specs


def strip_plotly_markers(text: str) -> str:
    """Remove PLOTLY_JSON markers from text, returning clean content."""
    return PLOTLY_PATTERN.sub("", text).strip()


def sanitize_for_supervisor(content: str, max_length: int = 2000) -> str:
    """Strip Plotly markers and truncate for Supervisor context.

    Prevents visualization data from polluting the Supervisor's context window.
    """
    content = PLOTLY_PATTERN.sub("[Chart generated — rendered in frontend]", content)
    if len(content) > max_length:
        content = content[:max_length] + "\n... [truncated]"
    return content
