"""Session-aware LangGraph registry keyed by effective model config."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from ..agents.analytics_agent import AnalyticsAgent
from ..agents.cypher_agent import CypherAgent
from ..agents.executor_agent import ExecutorAgent
from ..agents.optimization_agent import OptimizationAgent
from ..agents.planner_agent import PlannerAgent
from ..agents.report_agent import ReportAgent
from ..agents.supervisor_agent import SupervisorAgent
from ..core.graph import build_graph
from .model_loader import create_model, hash_session_model_config, has_runtime_api_keys
from .prompt_assembler import PromptAssembler

logger = logging.getLogger(__name__)
MAX_CACHED_GRAPHS = 16


class SessionGraphRegistry:
    """Build and cache compiled graphs per effective session model config."""

    def __init__(
        self,
        *,
        checkpointer: Any,
        session_config_loader: Callable[[str], Awaitable[dict[str, Any]]],
        prompt_assembler: PromptAssembler | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._session_config_loader = session_config_loader
        self._prompt_assembler = prompt_assembler or PromptAssembler()
        self._graphs: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_graph(self, session_id: str):
        """Return a compiled graph for the session's effective model config."""
        session_config = await self._session_config_loader(session_id)
        if has_runtime_api_keys(session_config):
            logger.info("Building non-cached session graph for %s due to runtime API keys", session_id)
            return self._build_graph(session_config)

        config_hash = hash_session_model_config(session_config, include_api_keys=False)

        graph = self._graphs.get(config_hash)
        if graph is not None:
            self._graphs.move_to_end(config_hash)
            return graph

        async with self._lock:
            graph = self._graphs.get(config_hash)
            if graph is not None:
                self._graphs.move_to_end(config_hash)
                return graph

            logger.info("Building session graph for config hash %s", config_hash[:12])
            graph = self._build_graph(session_config)
            self._graphs[config_hash] = graph
            while len(self._graphs) > MAX_CACHED_GRAPHS:
                self._graphs.popitem(last=False)
            return graph

    def _build_graph(self, session_config: dict[str, Any]):
        supervisor_agent = SupervisorAgent(
            model=create_model("supervisor_agent", session_config=session_config),
            plan_model=create_model("supervisor_agent", session_config=session_config),
            prompt_assembler=self._prompt_assembler,
        )
        cypher_agent = CypherAgent(
            model=create_model("cypher_agent", session_config=session_config)
        )
        analytics_agent = AnalyticsAgent(
            model=create_model("analytics_agent", session_config=session_config)
        )
        optimization_agent = OptimizationAgent(
            model=create_model("optimization_agent", session_config=session_config)
        )
        report_agent = ReportAgent(
            model=create_model("report_agent", session_config=session_config)
        )
        planner_agent = PlannerAgent(
            model=create_model("planner_agent", session_config=session_config),
            prompt_assembler=self._prompt_assembler,
        )
        executor_agent = ExecutorAgent(
            model=create_model("executor_agent", session_config=session_config),
        )

        return build_graph(
            supervisor_agent=supervisor_agent,
            cypher_agent=cypher_agent,
            analytics_agent=analytics_agent,
            optimization_agent=optimization_agent,
            report_agent=report_agent,
            planner_agent=planner_agent,
            executor_agent=executor_agent,
            checkpointer=self._checkpointer,
        )
