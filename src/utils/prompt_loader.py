"""Shared prompt template loader for all GRASS agents.

Loads prompt templates from src/prompts/ with caching to avoid
repeated disk I/O on every agent invocation.
"""

import functools
import os

_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "prompts"
)


@functools.lru_cache(maxsize=16)
def load_prompt(filename: str) -> str:
    """Load a prompt template from src/prompts/{filename}.

    Results are cached for the process lifetime (static files).
    """
    path = os.path.join(_PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
