"""Execute a single dashboard card Cypher query."""

import re

from .models import DashboardCardResult

MAX_DASHBOARD_ROWS = 500


def _normalize_cypher(cypher: str) -> str:
    return re.sub(r"\s+", " ", cypher.strip())


def execute_dashboard_card(
    *,
    gateway,
    card_id: str,
    cypher: str,
    expected_cypher: str,
    timeout_ms: int = 15000,
    max_rows: int = MAX_DASHBOARD_ROWS,
) -> DashboardCardResult:
    if _normalize_cypher(cypher) != _normalize_cypher(expected_cypher):
        return DashboardCardResult(
            cardId=card_id,
            status="error",
            executionMs=0,
            error="Card cypher mismatch",
        )
    try:
        result = gateway.read_cypher(cypher)
        execution_ms = result.execution_time_ms or 0
        if timeout_ms > 0 and execution_ms > timeout_ms:
            return DashboardCardResult(
                cardId=card_id,
                status="timeout",
                executionMs=execution_ms,
                error=f"Card exceeded timeout budget of {timeout_ms}ms",
            )
        if result.error:
            return DashboardCardResult(
                cardId=card_id,
                status="error",
                executionMs=execution_ms,
                error=result.error,
            )
        row_cap = max_rows if max_rows > 0 else MAX_DASHBOARD_ROWS
        rows = result.records[:row_cap]
        value = None
        if rows and "value" in rows[0]:
            raw = rows[0]["value"]
            if isinstance(raw, (int, float)):
                value = raw
        sampled = result.truncated or len(result.records) > row_cap
        return DashboardCardResult(
            cardId=card_id,
            status="success",
            value=value,
            rows=rows,
            executionMs=execution_ms,
            sampled=sampled,
            sampleNote=(
                f"Showing first {row_cap} rows"
                if sampled
                else None
            ),
        )
    except Exception as exc:
        return DashboardCardResult(
            cardId=card_id,
            status="error",
            executionMs=0,
            error=str(exc),
        )
