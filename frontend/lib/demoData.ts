/**
 * Pre-loaded demo data for showcase sessions.
 *
 * When the user selects a demo session from the sidebar, the corresponding
 * loader populates chatStore, agentStore, and databaseStore so all three
 * panels display realistic content without a running backend.
 */

import type { Message, PipelineRun, CypherResult } from "./types";

// ─── Session IDs (must match SQLite rows) ───────────────────────────────────

const OPTIMIZATION_SESSION_ID = "76cf9737-aa46-4d63-bc5d-772e53ad8910";

// ─── Helpers ────────────────────────────────────────────────────────────────

const TS = 1_770_675_400_000; // base timestamp for ordering

// ─── Optimization Query — Chat Messages ─────────────────────────────────────

const optimizationMessages: Message[] = [
  {
    id: "opt-user-1",
    role: "user",
    content:
      "I'm the procurement manager at Liberty View Creamery in Adams County. My top supplier provides over 50% of our raw milk. How do I de-risk my supply base while minimizing total sourcing cost?",
    timestamp: TS,
  },
  {
    id: "opt-assistant-1",
    role: "assistant",
    content: `GRASS analyzed your current supplier portfolio, identified alternative farms within 40 miles with spare capacity, cross-referenced risk exposure, and solved a mixed-integer linear program to find the cost-optimal diversified sourcing plan. Here are the results.

## Key Finding

**James Anderson Farm supplies 52.9% of your raw milk** (50,010 of 94,515 gal/mo), creating a dangerous single-point-of-failure. If that single farm goes offline, your remaining two suppliers can only deliver 44,505 gal/mo — just 39% of your target volume. The creamery would face a production shutdown.

## Optimized Supplier Portfolio

The MILP solver (optimal in 0.011s, MIP gap 0.01%) recommends expanding from 3 to 9 suppliers while capping any single supplier at 35% of total volume:

| Supplier | County | Vol (gal/mo) | Share | Dist (mi) | Landed $/gal | Status |
|----------|--------|-------------:|------:|----------:|--------------:|--------|
| Sisco Valley Farm LLC | York | 33,124 | 29.2% | 17.7 | $2.14 | NEW |
| Gutman Brothers | York | 26,293 | 23.2% | 18.1 | $2.23 | NEW |
| Wil-Ar Farms | Cumberland | 15,189 | 13.4% | 30.0 | $2.12 | NEW |
| Little Flower Farm | Cumberland | 14,615 | 12.9% | 26.2 | $2.12 | NEW |
| Crilon Acres | Lancaster | 11,173 | 9.9% | 37.5 | $2.11 | NEW |
| Hissong Mercer-Vu | Franklin | 7,024 | 6.2% | 38.9 | $2.22 | NEW |
| Jo Bo Holstein | Adams | 2,000 | 1.8% | 7.1 | $2.46 | RETAIN |
| Chamberlains Fairview | Franklin | 2,000 | 1.8% | 64.2 | $2.39 | RETAIN |
| James Anderson Farm | York | 2,000 | 1.8% | 33.3 | $2.40 | RETAIN |

## Current vs. Optimized Comparison

| Metric | Current | Optimized | Change |
|--------|--------:|----------:|-------:|
| Monthly volume | 94,515 gal | 113,418 gal | **+20%** |
| Suppliers | 3 | 9 | +6 |
| Max single-supplier share | 52.9% | 29.2% | **-23.7 pp** |
| HHI (concentration) | 3,930 | 1,883 | **-52%** |
| Weighted avg distance | 32.5 mi | 24.7 mi | -7.8 mi |
| Avg landed cost | $2.41/gal | $2.17/gal | **-$0.24/gal** |
| Monthly variable cost | $228,000 | $246,400 | +$18,400 |

## Risk Resilience — Worst-Case Analysis

**Current state:** If James Anderson Farm goes offline, only 44,505 gal/mo remains (39% of target). Two suppliers cannot sustain operations.

**Optimized state:** If Sisco Valley Farm (the new largest supplier) goes offline, 80,294 gal/mo remains (71% of target), and the remaining 8 suppliers can scale to ~201K gal/mo. The network absorbs the shock with surplus capacity.

## Interpretation

The optimization reveals a fundamental tension: **the current portfolio is cheap per gallon but fragile, while the optimized portfolio costs more total but is dramatically more resilient.**

The +$18,400/month in variable cost (+8%) buys three things the current portfolio entirely lacks:

1. **Concentration below regulatory thresholds** — HHI drops from 3,930 (highly concentrated) to 1,883 (moderately competitive). No single supplier exceeds 35%.

2. **Worst-case survivability** — losing the largest supplier goes from catastrophic (39% of demand met) to manageable (71% met, with headroom to scale). The creamery never faces a production shutdown scenario.

3. **20% volume growth** — the optimized portfolio sources 113,418 gal/mo, filling 20% more of the creamery's processing capacity. At yogurt margins of ~$1.50/gal, this growth generates an additional **$28,350/month in revenue** — more than offsetting the $18,400 cost increase.

The model retains all 3 existing suppliers at minimum volumes (2,000 gal/mo each) rather than severing relationships, preserving optionality to scale them back up if needed.

## Next Steps

1. **Contact Sisco Valley Farm and Gutman Brothers** first — they represent 52.4% of the new portfolio and are both within 18 miles.
2. **Negotiate 90-day trial contracts** with new suppliers at the landed cost targets above before committing to full volumes.
3. **Phase the transition over 3 months** — ramp new suppliers up while tapering James Anderson Farm from 50,010 to 2,000 gal/mo to avoid supply disruption.
4. **Set up quarterly portfolio reviews** using this GRASS pipeline to re-optimize as prices, capacities, and risk profiles change.`,
    timestamp: TS + 9300,
  },
];

// ─── Optimization Query — Agent Pipeline ────────────────────────────────────

const optimizationPipeline: PipelineRun = {
  messageId: "opt-assistant-1",
  query:
    "I'm the procurement manager at Liberty View Creamery in Adams County. My top supplier provides over 50% of our raw milk. How do I de-risk my supply base while minimizing total sourcing cost?",
  steps: [
    {
      id: "opt-step-1",
      agent: "Supervisor",
      status: "done",
      startedAt: TS + 100,
      completedAt: TS + 900,
      duration: 800,
      detail: { message: "Decomposed into 6 sub-tasks" },
    },
    {
      id: "opt-step-2",
      agent: "Cypher",
      status: "done",
      startedAt: TS + 1000,
      completedAt: TS + 3100,
      duration: 2100,
      detail: {
        message:
          "3 queries executed: supplier portfolio, alternatives within 40mi, risk cross-reference",
        cypherQuery:
          'MATCH (p:Processor {name: "Liberty View Creamery"})<-[s:SUPPLIES]-(f:Farm)\nRETURN f.name AS supplier, s.volume_gal AS monthly_volume,\n       round(s.volume_gal * 100.0 / 94515, 1) AS share_pct\nORDER BY s.volume_gal DESC',
        cypherPreview: [
          { supplier: "James Anderson Farm", monthly_volume: 50010, share_pct: 52.9 },
          { supplier: "Jo Bo Holstein", monthly_volume: 24120, share_pct: 25.5 },
          { supplier: "Chamberlains Fairview", monthly_volume: 20385, share_pct: 21.6 },
        ],
      },
    },
    {
      id: "opt-step-3",
      agent: "Analytics",
      status: "done",
      startedAt: TS + 3200,
      completedAt: TS + 4600,
      duration: 1400,
      detail: {
        message: "Transport cost model computed, optimization matrix prepared",
      },
    },
    {
      id: "opt-step-4",
      agent: "Optimization",
      status: "done",
      startedAt: TS + 4700,
      completedAt: TS + 7900,
      duration: 3200,
      detail: {
        message:
          "MILP solved: 9 suppliers, 7 constraint families, optimal in 0.011s",
      },
    },
    {
      id: "opt-step-5",
      agent: "Report",
      status: "done",
      startedAt: TS + 8000,
      completedAt: TS + 9800,
      duration: 1800,
      detail: { message: "Comparative analysis generated" },
    },
  ],
  plan: {
    intent: "optimization",
    summary:
      "De-risk Liberty View Creamery's supplier concentration by finding optimal diversified sourcing portfolio",
    steps: [
      { description: "Retrieve current supplier portfolio for Liberty View Creamery", agent: "Cypher" },
      { description: "Identify alternative dairy farms within 40mi with spare capacity", agent: "Cypher" },
      { description: "Cross-reference suppliers against risk events", agent: "Cypher" },
      { description: "Compute transport cost model and prepare optimization matrix", agent: "Analytics" },
      { description: "Solve MILP for cost-optimal diversified portfolio", agent: "Optimization" },
      { description: "Generate comparative analysis report", agent: "Report" },
    ],
    requires_geo: false,
    requires_optimization: true,
  },
  planDecision: "approved",
  startedAt: TS,
  completedAt: TS + 9300,
  totalDuration: 9300,
  receivedEvents: ["cypher_query", "report"],
};

// ─── Optimization Query — Database Results ──────────────────────────────────

const optimizationCypherResult: CypherResult = {
  query:
    'MATCH (p:Processor {name: "Liberty View Creamery"})<-[s:SUPPLIES]-(f:Farm)\nRETURN f.name AS supplier, s.volume_gal AS monthly_volume,\n       round(s.volume_gal * 100.0 / 94515, 1) AS share_pct\nORDER BY s.volume_gal DESC',
  columns: ["supplier", "monthly_volume", "share_pct"],
  rows: [
    { supplier: "James Anderson Farm", monthly_volume: 50010, share_pct: 52.9 },
    { supplier: "Jo Bo Holstein", monthly_volume: 24120, share_pct: 25.5 },
    { supplier: "Chamberlains Fairview", monthly_volume: 20385, share_pct: 21.6 },
  ],
};

// ─── Public API ─────────────────────────────────────────────────────────────

export interface DemoSessionData {
  messages: Message[];
  pipeline: PipelineRun;
  cypherResult: CypherResult;
}

const demoRegistry: Record<string, DemoSessionData> = {
  [OPTIMIZATION_SESSION_ID]: {
    messages: optimizationMessages,
    pipeline: optimizationPipeline,
    cypherResult: optimizationCypherResult,
  },
};

/**
 * Returns demo data for a session if it exists, or null for regular sessions.
 */
export function getDemoData(sessionId: string): DemoSessionData | null {
  return demoRegistry[sessionId] ?? null;
}
