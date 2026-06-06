"""LLM model factory and session-aware model configuration helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from copy import deepcopy
from typing import Any, Mapping

import yaml
from langchain.chat_models import init_chat_model

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "agent_models.yaml"
)

BACKEND_TO_FRONTEND_AGENT = {
    "supervisor_agent": "Supervisor",
    "cypher_agent": "Cypher",
    "analytics_agent": "Analytics",
    "optimization_agent": "Optimization",
    "report_agent": "Report",
}
FRONTEND_TO_BACKEND_AGENT = {
    frontend: backend for backend, frontend in BACKEND_TO_FRONTEND_AGENT.items()
}
MODEL_CAPABLE_AGENTS = tuple(FRONTEND_TO_BACKEND_AGENT.keys())
SUPPORTED_PROVIDERS = {"openai", "anthropic", "google", "ollama", "groq"}
SESSION_RUNTIME_KEY_PROVIDERS = ("openai", "anthropic", "google")
DEFAULT_SESSION_API_KEYS = {provider: "" for provider in SESSION_RUNTIME_KEY_PROVIDERS}
PROVIDER_ALIASES = {
    "google": "google_genai",
}


def load_config() -> dict:
    """Load agent model configuration from YAML file."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sanitize_model_config(provider: str, model_config: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize provider-specific config before model creation."""
    sanitized = dict(model_config)

    if provider == "openai":
        model_name = str(sanitized.get("model", ""))
        if model_name.startswith("gpt-5") and "temperature" in sanitized:
            temperature = sanitized.pop("temperature")
            logger.warning(
                "Dropping unsupported temperature=%s for OpenAI model %s; using provider default",
                temperature,
                model_name,
            )

    return sanitized


def get_default_session_model_config() -> dict[str, Any]:
    """Return the frontend-facing default config derived from YAML."""
    config = load_config()
    agent_defaults: dict[str, dict[str, str]] = {}

    for backend_agent, frontend_agent in BACKEND_TO_FRONTEND_AGENT.items():
        agent_config = config.get("agents", {}).get(backend_agent)
        if agent_config is None:
            raise ValueError(f"Agent '{backend_agent}' not found in config/agent_models.yaml")

        model_name = str(agent_config.get("model_config", {}).get("model", "")).strip()
        if not model_name:
            raise ValueError(f"Agent '{backend_agent}' is missing a model name")

        provider = str(agent_config.get("provider", "")).strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}' in defaults for {backend_agent}")

        agent_defaults[frontend_agent] = {
            "provider": provider,
            "model": model_name,
        }

    return {
        "agent_models": agent_defaults,
        "api_keys": dict(DEFAULT_SESSION_API_KEYS),
    }


def normalize_session_model_config(
    session_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate and merge a raw session model config with YAML defaults."""
    defaults = get_default_session_model_config()
    normalized = deepcopy(defaults)

    if not session_config:
        return normalized

    raw_agent_models = session_config.get("agent_models", {}) or {}
    if not isinstance(raw_agent_models, Mapping):
        raise ValueError("session_config.agent_models must be a mapping")

    for agent, agent_config in raw_agent_models.items():
        if agent not in MODEL_CAPABLE_AGENTS:
            raise ValueError(f"Unsupported agent override: {agent}")
        if not isinstance(agent_config, Mapping):
            raise ValueError(f"agent_models.{agent} must be an object")

        provider = str(agent_config.get("provider", "")).strip()
        model_name = str(agent_config.get("model", "")).strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}' for agent {agent}")
        if not model_name:
            raise ValueError(f"Agent {agent} must include a non-empty model name")

        normalized["agent_models"][agent] = {
            "provider": provider,
            "model": model_name,
        }

    raw_api_keys = session_config.get("api_keys", {}) or {}
    if not isinstance(raw_api_keys, Mapping):
        raise ValueError("session_config.api_keys must be a mapping")

    for provider, value in raw_api_keys.items():
        if provider not in DEFAULT_SESSION_API_KEYS:
            raise ValueError(f"Unsupported runtime API key provider: {provider}")
        normalized["api_keys"][provider] = str(value or "")

    return normalized


def resolve_agent_model_settings(
    agent_name: str,
    *,
    session_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the effective provider/model/settings for a backend agent."""
    config = load_config()
    agent_defaults = config.get("agents", {}).get(agent_name)
    if agent_defaults is None:
        raise ValueError(f"Agent '{agent_name}' not found in config/agent_models.yaml")

    frontend_agent = BACKEND_TO_FRONTEND_AGENT.get(agent_name)
    if frontend_agent is None:
        raise ValueError(f"No frontend agent mapping found for backend agent '{agent_name}'")

    provider = str(agent_defaults.get("provider", "")).strip()
    model_name = str(agent_defaults.get("model_config", {}).get("model", "")).strip()
    api_key = ""

    if session_config is not None:
        effective_session_config = normalize_session_model_config(session_config)
        model_override = effective_session_config["agent_models"][frontend_agent]
        provider = str(model_override["provider"])
        model_name = str(model_override["model"])
        api_key = str(effective_session_config.get("api_keys", {}).get(provider, "") or "")

    model_config = dict(agent_defaults.get("model_config", {}))
    model_config["model"] = model_name
    model_config = _sanitize_model_config(provider, model_config)

    return {
        "provider": provider,
        "model": model_config.pop("model"),
        "model_config": model_config,
        "api_key": api_key,
    }


def has_runtime_api_keys(session_config: Mapping[str, Any] | None) -> bool:
    """Return True when a session config includes runtime API keys."""
    normalized = normalize_session_model_config(session_config)
    return any(normalized.get("api_keys", {}).values())


def hash_session_model_config(
    session_config: Mapping[str, Any] | None,
    *,
    include_api_keys: bool = True,
) -> str:
    """Return a stable hash for the effective session model config."""
    normalized = normalize_session_model_config(session_config)
    if not include_api_keys:
        normalized["api_keys"] = dict(DEFAULT_SESSION_API_KEYS)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_provider_kwargs(provider: str, api_key: str) -> dict[str, Any]:
    """Map runtime credentials to provider-specific LangChain kwargs."""
    if not api_key:
        return {}

    if provider == "openai":
        return {"api_key": api_key}
    if provider == "anthropic":
        return {"anthropic_api_key": api_key}
    if provider == "google":
        return {"google_api_key": api_key}
    return {}


def create_model(
    agent_name: str,
    *,
    session_config: Mapping[str, Any] | None = None,
) -> Any:
    """Create a LangChain chat model for the given agent."""
    resolved = resolve_agent_model_settings(agent_name, session_config=session_config)
    provider = resolved["provider"]
    provider_name = PROVIDER_ALIASES.get(provider, provider)

    kwargs = {
        **resolved["model_config"],
        **_build_provider_kwargs(provider, resolved["api_key"]),
    }

    logger.info(
        "Creating %s model for %s: %s",
        provider,
        agent_name,
        resolved["model"],
    )

    return init_chat_model(
        model=resolved["model"],
        model_provider=provider_name,
        **kwargs,
    )
