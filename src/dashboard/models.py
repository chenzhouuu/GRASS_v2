"""Shared Pydantic models for dashboard v2 APIs."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CardKind = Literal[
    "kpi",
    "bar",
    "table",
    "map",
    "network",
    "sankey",
    "insight",
    "schemaGraph",
    "sampleGraph",
    "quality",
]
CardLayer = Literal["operational", "schema"]
CardStatus = Literal["success", "error", "timeout"]
CardSize = Literal["small", "medium", "large", "wide"]


class DashboardConnection(BaseModel):
    connected: bool
    uri: str
    database: str
    source: str


class DashboardContextResponse(BaseModel):
    connection: DashboardConnection
    fingerprint: str
    generatedAt: str
    warnings: list[str] = Field(default_factory=list)


class DashboardCardDrilldown(BaseModel):
    kind: Literal["cypher", "pattern", "label"] = "cypher"
    template: str


class DashboardCardDefinition(BaseModel):
    id: str
    layer: CardLayer
    type: CardKind
    title: str
    description: str
    cypher: str | None = None
    dataKey: str | None = None
    exact: bool = True
    priority: int = 100
    unit: str | None = None
    valueFormat: str | None = None
    size: CardSize = "small"
    timeoutMs: int = 15000
    maxRows: int = 500
    display: dict[str, Any] = Field(default_factory=dict)
    drilldown: DashboardCardDrilldown | None = None
    domain: str | None = None


class DashboardCatalogResponse(BaseModel):
    fingerprint: str
    cards: list[DashboardCardDefinition] = Field(default_factory=list)
    detectedLabels: list[str] = Field(default_factory=list)
    domainProfile: str = "generic"


class DashboardCardExecuteRequest(BaseModel):
    cardId: str
    cypher: str
    fingerprint: str
    timeoutMs: int = 15000


class DashboardCardResult(BaseModel):
    cardId: str
    status: CardStatus
    value: float | int | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    executionMs: int = 0
    error: str | None = None
    sampled: bool = False
    sampleNote: str | None = None
