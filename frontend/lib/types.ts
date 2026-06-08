// ─── Agent names matching the backend graph nodes ───────────────────────────

export type AgentName =
  | "Supervisor"
  | "Cypher"
  | "Analytics"
  | "Optimization"
  | "Report";

export type StreamAgentName = AgentName | "System";

// ─── Agent progress (SSE: agent_start / agent_complete / error) ─────────────

export type AgentStatusValue = "pending" | "running" | "done" | "error";

export interface AgentStatus {
  agent: StreamAgentName;
  status: AgentStatusValue;
  message?: string; // human-readable label e.g. "Querying Neo4j..."
  result?: unknown; // payload from agent_complete
  error?: string;   // payload from error event
}

// ─── Plan (SSE: plan) ───────────────────────────────────────────────────────

export interface PlanStep {
  description: string;
  agent: AgentName;
}

export interface GRASSPlan {
  intent: string; // factual_lookup | analytical | spatial | optimization | report | conversational | unclear
  summary?: string;
  steps: PlanStep[];
  requires_geo: boolean;
  requires_optimization: boolean;
}

export type PlanDecision = "approved" | "modified" | "cancelled";

// ─── Co-planning (SSE: plan_review / plan_pending) ──────────────────────────
// Mirrors the backend Plan/PlanStep contract (Magentic-UI port). Distinct from
// the legacy GRASSPlan/PlanStep above (which back the read-only `plan` event).

export interface CoPlanStep {
  title: string;
  details: string;
  agent: AgentName;
  enabled?: boolean;
}

export interface CoPlan {
  task?: string | null;
  summary?: string;
  steps: CoPlanStep[];
  requires_geo?: boolean;
  requires_optimization?: boolean;
}

export interface PlanReviewPayload {
  run_id: string;
  plan: CoPlan;
  plan_str?: string;
  summary?: string;
  message?: string;
}

// ─── Ledger execution progress (SSE: progress) ──────────────────────────────
// Live per-step checklist streamed while an approved plan runs through the
// progress-ledger Executor. Drives the execution-timeline UI.

export type LedgerStepStatus = "pending" | "running" | "done" | "error";

export type LedgerPhase = "executing" | "replanning" | "finalizing" | "complete";

export interface LedgerProgressStep {
  index: number;
  title: string;
  agent: AgentName;
  status: LedgerStepStatus;
}

export interface LedgerProgress {
  phase: LedgerPhase;
  current_step: number;
  total_steps: number;
  summary: string;
  steps: LedgerProgressStep[];
}

// ─── What-if scenario comparison (SSE: scenario_comparison) ─────────────────

export type GoodDirection = "up" | "down" | "flat";

export interface KpiDelta {
  name: string;
  baseline: number;
  scenario: number;
  delta: number;
  pct: number | null;
  unit: string;
  good_direction: GoodDirection;
}

export interface ScenarioComparison {
  baseline_run_id: string;
  scenario_run_id: string;
  scenario_name: string;
  scenario_description: string;
  objective_sense: string;
  objective_baseline: number | null;
  objective_scenario: number | null;
  kpi_deltas: KpiDelta[];
  binding_added: string[];
  binding_removed: string[];
  waterfall: { data: Plotly.Data[]; layout?: Partial<Plotly.Layout> } | null;
  narrative: string;
}

// ─── Chat messages ──────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

export interface MessageAttachment {
  id: string;
  name: string;
  type: "pdf" | "csv" | "chart" | "map";
  url?: string; // /api/files/{file_id}
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;          // markdown text
  timestamp: number;        // epoch ms
  agentProgress?: AgentStatus[];
  plan?: GRASSPlan;
  planDecision?: PlanDecision;
  ledgerProgress?: LedgerProgress;
  attachments?: MessageAttachment[];
  visualizations?: VisualizationData[];
  mapData?: MapPayload;
  scenarioComparison?: ScenarioComparison;
}

// ─── Cypher / Database (SSE: cypher_query) ──────────────────────────────────

export interface NvlGraphNode {
  id: string;
  labels?: string[];
  caption?: string;
  properties?: Record<string, unknown>;
}

export interface NvlGraphRelationship {
  id: string;
  from: string;
  to: string;
  type?: string;
  caption?: string;
  properties?: Record<string, unknown>;
}

export interface NvlGraphResult {
  nodes: NvlGraphNode[];
  relationships: NvlGraphRelationship[];
  stats?: {
    nodeCount: number;
    relationshipCount: number;
    truncated?: boolean;
  };
  warnings?: string[];
}

export type DatabaseResultsViewMode = "table" | "graph" | "raw";

export interface CypherResult {
  query: string;
  columns: string[];
  rows: Record<string, unknown>[];
  executionTimeMs?: number;
  error?: string;
  truncated?: boolean;
  source?: string;
  validationWarnings?: string[];
  graph?: NvlGraphResult | null;
  graphTruncated?: boolean;
  graphWarnings?: string[];
}

export interface SchemaNode {
  label: string;
  properties: string[];
}

export interface SchemaRelationship {
  type: string;
  properties: string[];
  pattern?: string | null;
}

export interface Neo4jSchema {
  nodes: SchemaNode[];
  relationships: SchemaRelationship[];
}

export interface SavedQuery {
  id: string;
  name: string;
  query: string;
  createdAt: number;
}

// ─── Map (SSE: map_data) ────────────────────────────────────────────────────

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  label: string;
  type?: string;            // node label, e.g. "Farm", "Company"
  properties?: Record<string, unknown>;
}

export type MapLayerType = "markers" | "heatmap" | "choropleth" | "routes";

export interface MapRoute {
  id: string;
  from: [number, number]; // [lat, lng]
  to: [number, number];
  label?: string;
  properties?: Record<string, unknown>;
}

export interface MapChoroplethRegion {
  id: string;
  geometry: Record<string, unknown>; // GeoJSON Geometry object
  value: number;
  label?: string;
}

export interface MapLayer {
  id: string;
  type: MapLayerType;
  visible: boolean;
  data: MapMarker[] | MapRoute[] | MapChoroplethRegion[] | [number, number][];
}

export interface MapViewport {
  center: [number, number]; // [lat, lng]
  zoom: number;
}

/** Payload shape from SSE map_data event */
export interface MapPayload {
  markers?: MapMarker[];
  layers?: MapLayer[];
}

// ─── Visualizations (SSE: visualization / chart_spec) ───────────────────────

export interface VisualizationData {
  id: string;
  type: "chart" | "table";
  title?: string;
  data: Record<string, unknown>; // Plotly spec or backend file reference
}

/** Payload from SSE chart_spec event — inline Plotly JSON spec */
export interface ChartSpecPayload {
  id: string;
  index: number;
  spec: {
    data: Plotly.Data[];
    layout?: Partial<Plotly.Layout>;
    config?: Partial<Plotly.Config>;
  };
}

/** Payload from SSE geo_data event — GeoJSON FeatureCollection */
export interface GeoDataPayload {
  geojson: GeoJSONFeatureCollection;
}

/** GeoJSON FeatureCollection (RFC 7946 subset) */
export interface GeoJSONFeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

export interface GeoJSONFeature {
  type: "Feature";
  geometry: {
    type: "Point" | "LineString" | "Polygon";
    coordinates: number[] | number[][]; // [lon, lat] or [[lon, lat], ...]
  };
  properties: Record<string, unknown>;
}

// ─── Sessions ───────────────────────────────────────────────────────────────

export interface Session {
  id: string;
  title: string;
  createdAt: number;  // epoch ms
  updatedAt: number;  // epoch ms
  messageCount: number;
  lastMessagePreview?: string;
}

// ─── Agent pipeline (for Agent tab in right panel) ──────────────────────────

export interface AgentCardDetail {
  cypherQuery?: string;
  cypherPreview?: Record<string, unknown>[];
  codeOutput?: string;
  error?: string;
  message?: string;
}

export interface AgentPipelineStep {
  id: string;
  agent: StreamAgentName;
  status: AgentStatusValue;
  startedAt: number | null;
  completedAt: number | null;
  duration: number | null;
  detail: AgentCardDetail;
}

export interface PipelineRun {
  messageId: string;
  query: string;
  steps: AgentPipelineStep[];
  plan: GRASSPlan | null;
  planDecision: PlanDecision | null;
  startedAt: number;
  completedAt: number | null;
  totalDuration: number | null;
  receivedEvents: string[];
}

// ─── SSE event union (for the stream handler) ───────────────────────────────

export type SSEEvent =
  | { event: "config_applied"; data: { agent_models: Record<string, { provider: string; model: string }> } }
  | { event: "agent_start"; data: { agent: AgentName; status: "running"; step_id: string } }
  | { event: "agent_complete"; data: { agent: AgentName; status: "done"; step_id?: string | null; result: unknown } }
  | { event: "cypher_query"; data: { query: string; results: Record<string, unknown>[] } }
  | { event: "analysis"; data: { summary: string; results: string } }
  | { event: "optimization"; data: { model: string; solution: Record<string, unknown>; status: string } }
  | { event: "chart_spec"; data: ChartSpecPayload }
  | { event: "geo_data"; data: GeoDataPayload }
  | { event: "map_data"; data: MapPayload }
  | { event: "report"; data: { url: string; title?: string } }
  | { event: "response"; data: { markdown: string } }
  | { event: "error"; data: { agent: StreamAgentName; step_id?: string | null; error: string } }
  | { event: "plan"; data: GRASSPlan }
  | { event: "plan_review"; data: PlanReviewPayload }
  | { event: "plan_pending"; data: { run_id: string } }
  | { event: "progress"; data: LedgerProgress }
  | { event: "scenario_comparison"; data: ScenarioComparison }
  | { event: "done"; data: Record<string, never> };
