# ELN Intelligence Platform — AI Insight Engine

## Developer tickets (phased implementation)

**Version:** 1.0 · **Date:** 18 June 2026 · **Owner:** Aqeedat Kaur Sandhu
**Target:** Add an Azure AI Foundry–based AI Insight Engine (experiment summarization + chemistry chat) to the live ELN Intelligence Platform.

---

## Assumed decisions (defaults — override before Phase 0 if needed)

These are the recommended answers to the five open decisions from the design doc. Work proceeds on these unless changed.

| # | Decision | Assumed default |
|---|----------|-----------------|
| 1 | Vector store | **Azure AI Search** (hybrid keyword + vector + semantic rank) |
| 2 | Patents source | **Grounding with Bing** for v1; dedicated patents API deferred to a later enhancement |
| 3 | Summary block | **On-demand with result caching** (no nightly precompute in v1) |
| 4 | Auth | **Re-enable EasyAuth first**, then build all AI endpoints behind it |
| 5 | Orchestration host | **Azure AI Foundry Agent Service** (managed) |

---

## Conventions

- **Subscription (nexus credits):** `9e25d11c-3753-4b8c-a575-0bcc44f964d4` — set before every CLI block.
- **Resource group:** `rg-eln-covvalent` unless a ticket states otherwise.
- **Ticket IDs:** `AIE-###`. **Estimates:** S ≈ ≤1 day, M ≈ 2–3 days, L ≈ 4–6 days.
- **Global Definition of Done:** code merged; deployed to the live environment; telemetry visible in `appi-eln-covvalent`; no secrets in code (Key Vault + Managed Identity only); acceptance criteria checked; short runbook note added to the platform context skill.

---

## Phase overview & dependency flow

```
Phase 0  Foundations & provisioning ──┬─> Phase 1  Indexing pipeline ──┐
                                       │                                ├─> Phase 3  Agent & orchestration ─> Phase 4  Frontend ─> Phase 5  Observability, eval, rollout
                                       └─> Phase 2  Retrieval tools ────┘
```

Phase 1 and Phase 2 can run in parallel once Phase 0 is done. Phase 3 needs both. Phase 5 runs alongside 3–4 and gates rollout.

---

# Phase 0 — Foundations & provisioning

Stand up the AI infrastructure and clear the auth prerequisite. No application logic yet.

### AIE-001 — Confirm region & quota for AI services
**Phase:** 0 · **Depends on:** — · **Estimate:** S
The platform runs in South India (B1 plan). Azure OpenAI (GPT-4o), `text-embedding-3-large`, and Azure AI Search are not guaranteed in every Indian region — repeat of the Central India B1/B2 availability problem we already hit.

**Acceptance criteria**
- [ ] Confirm a region (South India, Central India, or nearest) that has GPT-4o, `text-embedding-3-large`, and Azure AI Search capacity on the nexus subscription.
- [ ] Confirm Azure OpenAI TPM quota is sufficient for expected chat + embedding load; raise a quota request via the MfS channel if not.
- [ ] Document chosen region(s) and any cross-region latency implication (AI Search ↔ FastAPI ↔ OpenAI).

**Notes:** Cross-region calls are acceptable for v1 but note them; keep AI Search and OpenAI co-located if possible.

### AIE-002 — Provision Azure AI Foundry hub + project
**Phase:** 0 · **Depends on:** AIE-001 · **Estimate:** M
**Acceptance criteria**
- [ ] AI Foundry hub + project created in `rg-eln-covvalent` (nexus subscription), region per AIE-001.
- [ ] Project linked to `appi-eln-covvalent` for tracing and to `kv-eln-covvalent` for secrets.
- [ ] Access granted to platform admins; resource names recorded in the context skill.

### AIE-003 — Deploy Azure OpenAI model deployments
**Phase:** 0 · **Depends on:** AIE-002 · **Estimate:** S
**Acceptance criteria**
- [ ] `gpt-4o` deployment created (chat/reasoning).
- [ ] `text-embedding-3-large` deployment created (embeddings).
- [ ] Deployment names, endpoint, and API version recorded; a smoke-test completion and a smoke-test embedding both succeed.

### AIE-004 — Provision Azure AI Search
**Phase:** 0 · **Depends on:** AIE-001 · **Estimate:** S
**Acceptance criteria**
- [ ] AI Search service created in `rg-eln-covvalent` (Basic or S1 — size against ~1,699 experiments + sections; Basic is likely enough for v1).
- [ ] Semantic ranker enabled.
- [ ] Endpoint recorded; service reachable from the App Service.

### AIE-005 — Managed Identity role assignments (keyless auth)
**Phase:** 0 · **Depends on:** AIE-002, AIE-003, AIE-004 · **Estimate:** S
The FastAPI App Service identity (`principalId ae28ca27-bcc6-42ae-9b14-ee626710d3c9`) must reach OpenAI, AI Search, and Foundry without keys.

**Acceptance criteria**
- [ ] App Service MI granted `Cognitive Services OpenAI User` on the OpenAI resource.
- [ ] App Service MI granted `Search Index Data Reader` (query) on AI Search; the indexer identity granted `Search Index Data Contributor`.
- [ ] App Service MI granted the appropriate Foundry/Agent data role.
- [ ] Existing Key Vault access confirmed (RBAC vault — use `az role assignment create` with `Key Vault Secrets User`, never `set-policy`).

### AIE-006 — Re-enable EasyAuth on FastAPI (auth prerequisite)
**Phase:** 0 · **Depends on:** — · **Estimate:** M · **Priority:** blocker for any authenticated AI endpoint
Resolves platform open item #1 (JWT `aud` claim mismatch — dashboard MSAL token scoped to `api://f9c1c1ef-…/ELN.Read` is rejected by EasyAuth).

**Acceptance criteria**
- [ ] Root cause of the `aud` mismatch identified (token audience vs EasyAuth expected audience / `allowedAudiences`).
- [ ] EasyAuth re-enabled on `eln-api-covvalent` with `platform.enabled=true`.
- [ ] A dashboard-issued MSAL token successfully authenticates against an existing endpoint (e.g. `/api/dashboard/summary`).
- [ ] Regression check: all existing endpoints still serve authenticated requests.

---

# Phase 1 — Offline indexing pipeline

Build the searchable experiment corpus that powers "related chemistries we've worked on." Runs after the existing nightly ETL.

### AIE-101 — Design the AI Search index schema
**Phase:** 1 · **Depends on:** AIE-004 · **Estimate:** M
**Acceptance criteria**
- [ ] Index schema defined: chunk text + vector field (1536-dim or model-native), plus filterable/facetable metadata (`experiment_id`, `exp_number_full`, `project_code`, `team`, `scientist`, `date`, `section_type`, `has_yield`).
- [ ] Chunking strategy chosen (per-experiment with section-level sub-chunks; keep materials/products/TLC attached as metadata or structured fields).
- [ ] Hybrid + semantic query profile defined.
- [ ] Schema reviewed against the source tables: `eln_experiments` (1,699), `eln_experiment_sections` (13,705), `eln_experiment_materials`, `eln_experiment_products`, `eln_experiment_tlc`.

### AIE-102 — Build the indexer job (chunk + embed + upsert)
**Phase:** 1 · **Depends on:** AIE-101, AIE-003, AIE-005 · **Estimate:** L
**Acceptance criteria**
- [ ] Indexer reads new/changed experiments from ELNAnalytics (`SERVER=10.0.0.4,1433`, `eln_reader`).
- [ ] Chunks each experiment per AIE-101, embeds with `text-embedding-3-large`, upserts into AI Search.
- [ ] Idempotent: re-running does not duplicate documents (stable doc keys on `experiment_id` + chunk index).
- [ ] Errors logged to `appi-eln-covvalent`; partial failures don't abort the whole run.

**Notes:** Host as a Function App or Container App job. If a Function App is used, **do not set `WEBSITE_CONTENTOVERVNET=1`** — it silently kills the Python worker (prior incident). Container App job is the safer default.

### AIE-103 — Initial backfill of the full corpus
**Phase:** 1 · **Depends on:** AIE-102 · **Estimate:** S
**Acceptance criteria**
- [ ] All 1,699 experiments embedded and indexed.
- [ ] Spot-check: a known experiment is retrievable by `exp_number_full` and by a semantic query describing its chemistry.
- [ ] One-time embedding cost recorded against nexus credits.

### AIE-104 — Hook incremental sync to the nightly ETL
**Phase:** 1 · **Depends on:** AIE-102 · **Estimate:** M
**Acceptance criteria**
- [ ] Indexer triggers after `ELN_ETL_NightlySync` (2 AM) completes — via a change-watermark, ETL-completion signal, or scheduled offset.
- [ ] Only new/changed experiments since the last run are processed.
- [ ] A row is written to a sync-log (or `eln_etl_log` pattern) for each run with counts and status.
- [ ] Verified end-to-end: an experiment added to the source appears in semantic search the next morning.

---

# Phase 2 — Retrieval tools

Three callable tools the agent uses. Each has a clear input/output contract (function-calling schema).

### AIE-201 — Tool 1: structured SQL retrieval
**Phase:** 2 · **Depends on:** AIE-006 · **Estimate:** M
Reuses the existing FastAPI data layer — exact figures, not semantic guesses.

**Acceptance criteria**
- [ ] Tool exposes scoped, parameterized reads: experiment detail, project experiments, materials/products/TLC, dashboard stats.
- [ ] Read-only; parameterized queries only (no string-built SQL); respects existing row scoping.
- [ ] Function schema documented (name, params, return shape) for agent registration.

### AIE-202 — Tool 2: semantic search over the ELN corpus
**Phase:** 2 · **Depends on:** AIE-101, AIE-103 · **Estimate:** M
**Acceptance criteria**
- [ ] Tool runs a hybrid (keyword + vector + semantic-rank) query against the AI Search index.
- [ ] Supports metadata filters (project, scientist, date range, has-yield).
- [ ] Returns top-k chunks with `experiment_id` / `exp_number_full` so answers can cite the source experiment.
- [ ] Function schema documented.

### AIE-203 — Tool 3: literature & patent search
**Phase:** 2 · **Depends on:** AIE-002 · **Estimate:** M
**Acceptance criteria**
- [ ] Grounding-with-Bing tool wired and callable; returns titles, snippets, and source URLs.
- [ ] Results carry citations the agent can surface.
- [ ] Any required key stored in `kv-eln-covvalent`; no key in code.
- [ ] Function schema documented. (Dedicated patents API explicitly out of scope for v1 — backlog item AIE-503.)

---

# Phase 3 — Agent & orchestration

Assemble the engine and expose it through FastAPI.

### AIE-301 — Author the skill-grounding instruction layer
**Phase:** 3 · **Depends on:** — (can start early) · **Estimate:** L
The engine's behaviour comes from three process-chemistry methodologies, supplied as system prompt + few-shot — not code.

**Acceptance criteria**
- [ ] System prompt composed from: `chemist-analyst` (mechanism/kinetics/route/safety reasoning + literature-and-patent research protocol; output-format sections excluded), `rnd-meeting-copilot` (senior-chemist persona + priority-ordered, early-stopping experiment queue with stop rules), `experimental-review-design` (gaps → review → conclusion → next experiments).
- [ ] Few-shot examples curated (e.g. from the Suzuki coupling example) showing the expected summary + next-steps shape.
- [ ] Explicit "never fabricate; cite the source experiment or literature; ask if ambiguous" guardrail wording included.
- [ ] Reviewed by a chemist (Dr. Saxena) for persona fidelity.

### AIE-302 — Create the Foundry agent and register tools
**Phase:** 3 · **Depends on:** AIE-201, AIE-202, AIE-203, AIE-301 · **Estimate:** M
**Acceptance criteria**
- [ ] Agent created in the Foundry project, using the `gpt-4o` deployment and the AIE-301 instructions.
- [ ] All three tools registered with correct schemas.
- [ ] Manual test: agent answers a sample question by calling structured + semantic + literature tools and returns a grounded summary with next steps.

### AIE-303 — `POST /api/ai/chat` (streaming) on FastAPI
**Phase:** 3 · **Depends on:** AIE-302, AIE-006 · **Estimate:** L
**Acceptance criteria**
- [ ] Endpoint accepts a question + conversation/session id, behind EasyAuth.
- [ ] Invokes the agent; streams the response (SSE or chunked) back to the client.
- [ ] Returns citations (source experiments + literature) alongside the answer.
- [ ] Per-request trace (tokens, tool calls, latency) emitted to App Insights.
- [ ] Handles tool errors and model timeouts gracefully with a user-facing fallback.

### AIE-304 — `GET /api/ai/summary` (experiment / project summary)
**Phase:** 3 · **Depends on:** AIE-302 · **Estimate:** M
**Acceptance criteria**
- [ ] Endpoint summarizes a given experiment, campaign, or project (details + findings).
- [ ] Result cached (per the on-demand-with-caching decision) keyed by entity id + data version; cache invalidated when the entity is re-indexed.
- [ ] Falls back cleanly if the entity has no data.

### AIE-305 — Conversation/session handling
**Phase:** 3 · **Depends on:** AIE-303 · **Estimate:** M
**Acceptance criteria**
- [ ] Multi-turn context preserved within a session.
- [ ] Session storage chosen (Foundry thread state vs lightweight store); retention policy defined.
- [ ] Token-budget management so long threads don't blow context limits.

---

# Phase 4 — Frontend (Static Web App)

Surface the engine in the existing React dashboard.

### AIE-401 — Chat panel component
**Phase:** 4 · **Depends on:** AIE-303 · **Estimate:** L
**Acceptance criteria**
- [ ] Chat panel added to the dashboard; sends question + MSAL token to `/api/ai/chat`.
- [ ] Streams and renders the answer incrementally.
- [ ] Renders citations as links to the referenced experiment(s) and external sources.
- [ ] Loading, error, and empty states handled.

### AIE-402 — Summary block on experiment / project views
**Phase:** 4 · **Depends on:** AIE-304 · **Estimate:** M
**Acceptance criteria**
- [ ] "AI summary" block on experiment and project pages calls `/api/ai/summary`.
- [ ] Shows cached result instantly when available; spinner + progressive render otherwise.
- [ ] A refresh control re-requests the summary.

### AIE-403 — Deploy SWA with the new UI
**Phase:** 4 · **Depends on:** AIE-401, AIE-402 · **Estimate:** S
**Acceptance criteria**
- [ ] Built and deployed via SwaCli (existing manual flow) to `eln-dashboard-covvalent`.
- [ ] Auth flow verified end-to-end: dashboard → token → EasyAuth → AI endpoints.
- [ ] Smoke test on the live URL passes.

---

# Phase 5 — Observability, evaluation, safety, cost & rollout

Gates production rollout. Runs alongside Phases 3–4.

### AIE-501 — Tracing & dashboards
**Phase:** 5 · **Depends on:** AIE-303 · **Estimate:** M
**Acceptance criteria**
- [ ] App Insights captures per-request tokens, latency, tool-call counts, and errors.
- [ ] A dashboard/workbook shows usage, latency percentiles, and daily token spend.
- [ ] Alerts on error-rate and latency thresholds.

### AIE-502 — Evaluation harness
**Phase:** 5 · **Depends on:** AIE-302 · **Estimate:** L
**Acceptance criteria**
- [ ] A gold-set of ~20–30 chemist-authored Q→expected-shape pairs.
- [ ] Automated checks for groundedness (claims trace to a retrieved source) and citation accuracy.
- [ ] Chemist (Dr. Saxena) sign-off on a sample of summaries and next-step plans before rollout.

### AIE-503 — Safety & guardrails
**Phase:** 5 · **Depends on:** AIE-302 · **Estimate:** M
**Acceptance criteria**
- [ ] Azure AI Content Safety / Foundry guardrails enabled on the agent.
- [ ] Retrieved web/literature content is treated as untrusted data, not instructions (prompt-injection mitigation).
- [ ] No experiment data sent to external endpoints other than the configured grounding tool.
- [ ] (Backlog) dedicated patents-API integration scoped here for a future version.

### AIE-504 — Cost monitoring & MfS key-services threshold
**Phase:** 5 · **Depends on:** AIE-501 · **Estimate:** S
**Acceptance criteria**
- [ ] Monthly token + AI Search + grounding spend tracked against nexus credits.
- [ ] Confirm the added Azure Monitor / Log Analytics / App Insights usage contributes to the $100/month key-services threshold for the full MfS credit envelope.
- [ ] A cost note prepared for the next milestone review with Ea Takano.

### AIE-505 — Rollout
**Phase:** 5 · **Depends on:** AIE-403, AIE-502, AIE-503 · **Estimate:** S
**Acceptance criteria**
- [ ] Internal pilot with the R&D team; feedback collected.
- [ ] Go/no-go on eval results, safety checks, and cost.
- [ ] Runbook and context-skill updates merged; engine announced as available.

---

## Ticket index

| ID | Title | Phase | Est |
|----|-------|-------|-----|
| AIE-001 | Confirm region & quota | 0 | S |
| AIE-002 | Provision AI Foundry hub + project | 0 | M |
| AIE-003 | Deploy Azure OpenAI models | 0 | S |
| AIE-004 | Provision Azure AI Search | 0 | S |
| AIE-005 | Managed Identity role assignments | 0 | S |
| AIE-006 | Re-enable EasyAuth (blocker) | 0 | M |
| AIE-101 | Design AI Search index schema | 1 | M |
| AIE-102 | Build indexer job | 1 | L |
| AIE-103 | Initial corpus backfill | 1 | S |
| AIE-104 | Hook incremental sync to ETL | 1 | M |
| AIE-201 | Tool 1: structured SQL retrieval | 2 | M |
| AIE-202 | Tool 2: semantic search | 2 | M |
| AIE-203 | Tool 3: literature & patents | 2 | M |
| AIE-301 | Author skill-grounding instructions | 3 | L |
| AIE-302 | Create Foundry agent + register tools | 3 | M |
| AIE-303 | /api/ai/chat (streaming) | 3 | L |
| AIE-304 | /api/ai/summary | 3 | M |
| AIE-305 | Conversation/session handling | 3 | M |
| AIE-401 | Chat panel component | 4 | L |
| AIE-402 | Summary block on views | 4 | M |
| AIE-403 | Deploy SWA with new UI | 4 | S |
| AIE-501 | Tracing & dashboards | 5 | M |
| AIE-502 | Evaluation harness | 5 | L |
| AIE-503 | Safety & guardrails | 5 | M |
| AIE-504 | Cost monitoring & MfS threshold | 5 | S |
| AIE-505 | Rollout | 5 | S |

---

*Private & Confidential — Covvalent (Rainboweucalyptus Technologies Pvt. Ltd.)*
