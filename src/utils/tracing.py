"""LangSmith tracing configuration for GRASS.

Call ``configure_tracing()`` once at startup (before building the graph).
When the required environment variables are present, all LangChain /
LangGraph calls are automatically traced to LangSmith — no extra code
changes are needed in agents or tools.

Required env vars (set in ``.env``):
    LANGCHAIN_API_KEY       – LangSmith API key
    LANGCHAIN_TRACING_V2    – set to "true" to enable
    LANGCHAIN_PROJECT       – project name in LangSmith (default: "grass")

Optional:
    LANGCHAIN_ENDPOINT      – custom LangSmith endpoint
                              (default: https://api.smith.langchain.com)
"""

import logging
import os

logger = logging.getLogger(__name__)


def configure_tracing(
    *,
    project_name: str | None = None,
    enabled: bool | None = None,
) -> bool:
    """Set up LangSmith tracing from environment variables.

    Parameters
    ----------
    project_name : str, optional
        Override the LangSmith project name.  Falls back to the
        ``LANGCHAIN_PROJECT`` env var, then ``"grass"``.
    enabled : bool, optional
        Explicitly enable / disable tracing.  When *None* (the default),
        tracing is enabled only when ``LANGCHAIN_API_KEY`` is set **and**
        ``LANGCHAIN_TRACING_V2`` is ``"true"`` (or not set — we default
        it to ``"true"`` when a key is present).

    Returns
    -------
    bool
        Whether tracing was successfully enabled.
    """

    api_key = os.environ.get("LANGCHAIN_API_KEY", "").strip()

    # Explicit disable
    if enabled is False:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("LangSmith tracing explicitly disabled.")
        return False

    # Determine if we should trace
    tracing_env = os.environ.get("LANGCHAIN_TRACING_V2", "").strip().lower()

    if enabled is True:
        should_trace = True
    elif api_key:
        # If key is present, default to enabled unless explicitly set to "false"
        should_trace = tracing_env != "false"
    else:
        should_trace = False

    if not should_trace:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info(
            "LangSmith tracing disabled (no LANGCHAIN_API_KEY or "
            "LANGCHAIN_TRACING_V2 set to false)."
        )
        return False

    if not api_key:
        logger.warning(
            "LangSmith tracing requested but LANGCHAIN_API_KEY is not set. "
            "Tracing will NOT be active."
        )
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    # ── Enable tracing ──────────────────────────────────────────────
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key

    resolved_project = (
        project_name
        or os.environ.get("LANGCHAIN_PROJECT", "").strip()
        or "grass"
    )
    os.environ["LANGCHAIN_PROJECT"] = resolved_project

    # Optional endpoint override
    endpoint = os.environ.get("LANGCHAIN_ENDPOINT", "").strip()
    if not endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

    logger.info(
        "LangSmith tracing enabled  ·  project=%s  ·  endpoint=%s",
        resolved_project,
        os.environ["LANGCHAIN_ENDPOINT"],
    )
    return True


def is_tracing_enabled() -> bool:
    """Return True if LangSmith tracing is currently active."""
    return (
        os.environ.get("LANGCHAIN_TRACING_V2", "").strip().lower() == "true"
        and bool(os.environ.get("LANGCHAIN_API_KEY", "").strip())
    )
