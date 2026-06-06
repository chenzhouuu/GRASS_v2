"""Neo4j driver setup and runtime connection management."""

import json
import os
import logging
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

logger = logging.getLogger(__name__)


class Neo4jConfig(TypedDict):
    uri: str
    username: str
    password: str
    database: str


DEFAULT_NEO4J_CONFIG: Neo4jConfig = {
    "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    "username": os.getenv("NEO4J_USERNAME", "neo4j"),
    "password": os.getenv("NEO4J_PASSWORD", ""),
    "database": os.getenv("NEO4J_DATABASE", "neo4j"),
}

_active_config: Neo4jConfig = deepcopy(DEFAULT_NEO4J_CONFIG)
_config_source = "env"

_driver = None
_OVERRIDE_FILE = Path("data/neo4j_override.json")


def _save_override_to_file(config: Neo4jConfig) -> None:
    """Persist a runtime Neo4j config override to disk."""
    try:
        _OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OVERRIDE_FILE.write_text(json.dumps(dict(config), indent=2))
        logger.info("Neo4j override config saved to %s", _OVERRIDE_FILE)
    except Exception:
        logger.warning("Failed to save Neo4j override config", exc_info=True)


def _load_override_from_file() -> Neo4jConfig | None:
    """Load a previously persisted Neo4j config override from disk."""
    if not _OVERRIDE_FILE.exists():
        return None
    try:
        data = json.loads(_OVERRIDE_FILE.read_text())
        config: Neo4jConfig = {
            "uri": str(data.get("uri", "")),
            "username": str(data.get("username", "")),
            "password": str(data.get("password", "")),
            "database": str(data.get("database", "")),
        }
        if config["uri"] and config["username"]:
            logger.info("Loaded Neo4j override config from %s", _OVERRIDE_FILE)
            return config
    except Exception:
        logger.warning("Failed to load Neo4j override config", exc_info=True)
    return None


def _build_driver(config: Neo4jConfig):
    return GraphDatabase.driver(
        config["uri"],
        auth=(config["username"], config["password"]),
    )


def get_neo4j_config() -> Neo4jConfig:
    """Return the active Neo4j runtime config."""
    return deepcopy(_active_config)


def get_driver():
    """Return a singleton Neo4j driver, creating it on first call."""
    global _driver
    if _driver is None:
        config = get_neo4j_config()
        logger.info("Creating Neo4j driver for %s", config["uri"])
        _driver = _build_driver(config)
    return _driver


def close_driver():
    """Shut down the singleton driver (call at application exit)."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


@contextmanager
def get_session():
    """Yield a Neo4j session scoped to the configured database."""
    driver = get_driver()
    session = driver.session(database=_active_config["database"])
    try:
        yield session
    finally:
        session.close()


def verify_connectivity(config: Neo4jConfig | None = None):
    """Test that the driver can reach the Neo4j server.

    Returns True on success, raises on failure.
    """
    if config is None:
        driver = get_driver()
        driver.verify_connectivity()
        logger.info("Neo4j connectivity verified (%s)", _active_config["uri"])
        return True

    driver = _build_driver(config)
    try:
        driver.verify_connectivity()
        logger.info("Neo4j connectivity verified for override (%s)", config["uri"])
        return True
    finally:
        driver.close()


def apply_runtime_neo4j_config(config: Neo4jConfig) -> dict[str, object]:
    """Verify and apply a runtime Neo4j config override."""
    global _active_config, _config_source
    verify_connectivity(config)
    close_driver()
    _active_config = deepcopy(config)
    _config_source = "runtime_override"
    _save_override_to_file(_active_config)
    # Eagerly create the new driver so failures happen during apply, not later.
    verify_connectivity()
    return get_neo4j_runtime_state()


def get_neo4j_runtime_state() -> dict[str, object]:
    """Return current config and live connectivity state."""
    connected = True
    try:
        verify_connectivity()
    except Exception:
        connected = False

    return {
        **get_neo4j_config(),
        "connected": connected,
        "source": _config_source,
    }


def initialize_default_connection() -> bool:
    """Try the default env config once at startup without crashing callers.

    If a runtime override file exists from a previous session, try that first.
    """
    global _active_config, _config_source

    # Check for persisted runtime override from a previous server session
    override = _load_override_from_file()
    if override is not None:
        close_driver()
        _active_config = deepcopy(override)
        _config_source = "runtime_override"
        try:
            verify_connectivity()
            logger.info("Neo4j connected using persisted override config")
            return True
        except Exception:
            logger.warning(
                "Persisted Neo4j override config failed, falling back to .env defaults",
                exc_info=True,
            )

    # Fall back to .env defaults
    _active_config = deepcopy(DEFAULT_NEO4J_CONFIG)
    _config_source = "env"
    close_driver()
    try:
        verify_connectivity()
        return True
    except Exception:
        logger.warning("Neo4j default connectivity check failed", exc_info=True)
        return False
