# Roadmap: enhancements to build when budget allows

Ideas the owner wants built later, written down with enough detail to blueprint without redoing the research. Each
entry says what it shows, which Couchbase feature carries it, what it needs, where it fits in `docs/SPEC.md`'s phases,
and what is still unknown. Status is **idea** until the architect blueprints it into `docs/workstreams/`.

The product page and the architecture notes describe the AI Data Plane items below as possibilities, not as part of
the demo. The demo runs on Capella; the AI Data Plane is also offered on self-managed Couchbase Server Enterprise
Edition, which matters to anyone running the repo on their own cluster.

## Couchbase AI Data Plane (AIDP)

Facts checked against Couchbase's documentation on 2026-10-09. The AI Data Plane (formerly Capella AI Services) is
offered self-managed with Couchbase Server Enterprise Edition or fully managed on Capella; several parts need an
Enterprise support tier. Confirm per-feature availability on the demo's Capella cluster (and, for readers, on a
self-managed cluster) before blueprinting (open question R0 below).

| Part | What it is | Notes |
|---|---|---|
| Model Service | Deploy LLMs and embedding models, or bring OpenAI or Amazon Bedrock models | Enterprise support only. Per deployment: standard caching (exact prompt and parameters), semantic caching (the prompt is embedded and a close match within a score threshold is returned; needs a deployed embedding model), a combined mode chosen per request with the `X-cb-cache` header (`standard`, `semantic`, `none`), a TTL (default 4,000 s, 3,600 to 604,800), async processing, guardrails, jailbreak detection, keyword filters (up to 10). Changing these after deployment invalidates the deployment's API keys. |
| AI Functions | SQL++ functions: `ai_summary`, `ai_classification`, `ai_extraction`, `ai_sentiment`, `ai_masked`, `ai_translation`, `ai_similarity`, `ai_corrected_grammar`, `ai_generated_text`, `ai_completion` | On Capella: a paid cluster on Couchbase Server 8.0+, multiple availability zones, Developer Pro or Enterprise support. Backed by a Model Service model, OpenAI or Bedrock. |
| Data Processing (vectorization) | Workflows you start over data already in the cluster, or PDFs, images and JSON from S3 | Enterprise support only. Does not vectorize on write. 100 MB per file, 10,000 files per workflow. |
| Agent Catalog | A versioned store of tools and prompts (not a runtime; your framework runs the tools); git is the version source | Tools: Python functions (`@agentc.catalog.tool`), `.sqlpp` query files with a YAML header, YAML semantic-search tools over a vector index, YAML OpenAPI/HTTP tools. Prompts in `.prompt` files. `agentc` CLI (`init`, `add`, `index`, `publish`, `clean`); the catalog is local JSON under `.agent-catalog/` and is published to an `agent_catalog` scope. Helpers for LangChain, LangGraph and LlamaIndex. |
| Agent Tracer | Audit of agent activity: tool calls, results, handoffs, model outputs | Logs to `./agent-activity` by default. |
| Agent Memory | Persistent per-user memory across sessions | Enterprise support only. |
| MCP Server | Self-hosted MCP server: SQL++ queries, schema listing, document reads and writes | Has a read-only mode; read-only is not the default. |

Sources: [AIDP overview](https://docs.couchbase.com/ai/get-started/intro.html) ·
[Model Service](https://docs.couchbase.com/ai/build/model-service/model-service.html) ·
[Deploy an LLM](https://docs.couchbase.com/ai/build/model-service/deploy-llm-model.html) ·
[Configure caching](https://docs.couchbase.com/ai/build/model-service/configure-value-adds.html) ·
[Agent Catalog](https://docs.couchbase.com/ai/build/integrate-agent-with-catalog.html) ·
AI Functions, Data Processing and MCP Server facts as recorded in fieldproof's `docs/REFERENCE.md` (checked 2026-09-24).

### R1. Agent Catalog as the single source of the agents' tools and prompts (Phase 2 to 3) — idea

- **Shows:** every agent's tools and prompts are versioned in the database, and every agent output is stamped with the
  exact tool and prompt version (the provenance rule in `docs/SPEC.md` section 6.1). Agent Tracer gives the "show its
  work" beat.
- **Tools to catalogue:** the conservation query and the exception queue as `.sqlpp` tools; HQ's HTTP API
  (`ports/hq.md`) and the box agent's API (`ports/box-agent.md`) as OpenAPI tools; ordinances as a semantic-search
  tool over a vector index.
- **Answers a spec open question** (section 11: does Agent Catalog cover on-box agents?): the catalog exists as local
  JSON, so the box could carry a snapshot from its last sync and run tools offline. Unverified.
- **Needs:** Python agent framework choice (LangGraph is supported); the HQ and box APIs as OpenAPI specs.

### R2. Reconciliation assistant (Phase 2) — idea

- **Shows:** at rejoin, for each open exception, an agent drafts a proposed resolution with its evidence (both
  branches, each branch's leaf, the clerks' notes, the devices' unpushed tails). HQ decides; the agent never writes a
  resolution (decision 007: HQ is the authority; decision 008: HQ's clock orders HQ's decisions).
- **Uses:** R1's tools, the Model Service, Agent Tracer.
- **Guard:** the draft is stored as advice (its own document kind, never `exception.resolution`).

### R3. Trip-close checker (Phase 2) — idea

- **Shows:** after the device closes (decision 007, #81), an agent compares each manifest and its Z figures with HQ's
  recomputation and explains any gap in plain English ("tablet-b says ten sales; HQ holds nine; one movement pending").
- **Depends on:** the Phase 2 close design (#81).

### R4. Semantic caching on the "terrible link" (Phase 2) — idea

- **Shows:** on a weak uplink, a cached answer returns at once, so a short connectivity window is enough. The HQ screen
  shows cache hits and model calls saved.
- **Targets:** "why this upsell" explanations when online; compliance questions ("do I need a permit at this venue?");
  the venue scorer's narratives.
- **Guard (a design rule we enforce, not a product guarantee):** jurisdiction and store go into the system prompt or
  the cache key so one city's answer is never served to another (the `jurisdiction_match` provenance check). The docs
  do not say whether the system prompt must match exactly; verify before relying on it.
- **Needs:** a Model Service LLM deployment with semantic caching on, and a deployed embedding model.

### R5. AI Functions in SQL++ (Phase 2) — idea

Each is one statement, like the conservation query.
- `ai_extraction` turns clerk free text ("asked for a size L in olive") into structured `demand_signal` documents.
- `ai_summary` writes a one-line summary of each dispute on HQ's queue, and a plain-English trip report from the sales
  and conservation rows.
- `ai_masked` hides member data before a trip report leaves the organisation.
- `ai_translation` for a venue in another language.
- **Guard:** summaries are labelled as generated and never replace the evidence (provenance rule).

### R6. Product and ordinance embeddings through Data Processing (Phase 1 and 3) — idea

- **Shows:** "embedded in the cluster, searched offline on the tablet": a workflow embeds the catalog, the vectors sync
  down, and the tablet's on-device vector search (Phase 1 upsell) uses them. A second workflow vectorizes ordinance
  PDFs from S3 for the compliance agent.
- **Note:** workflows are started, not triggered on write; re-run after catalog changes.

### R7. Guardrails, jailbreak detection and keyword filters (any phase) — idea

On every clerk- or audience-facing model call. Cheap to switch on; changing them invalidates the deployment's keys.

### R8. Mentions, not builds — idea

- MCP Server, read-only, for an HQ "ask the ledger" assistant.
- Agent Memory for per-venue memory ("last time at Riverfest it rained").

### Open questions

- **R0.** Which AIDP parts are available on the demo's Capella cluster and support tier (AI Functions need a paid
  cluster on Server 8.0+ with multiple availability zones and Developer Pro or Enterprise support), and which on
  self-managed Server Enterprise Edition?
- Does Agent Catalog's local JSON catalog work on the box with no connection (R1)?
- Does semantic caching hash the system prompt exactly (R4)?

## Deferred elsewhere

- Device and trip closes, manifests, and settled-versus-live facts: Phase 2, designed in #81 (decision 007).
- Per-device sequence numbers: studied and rejected (#77).
