# Covvalent ELN Intelligence Platform — Full Context
> **For Claude Code:** Read this file at the start of every session before making any changes.
> Last updated: 24 June 2026

---

## How to use this file with Claude Code

1. Save this file as `ELN_PLATFORM_CONTEXT.md` in your project root:
   `C:\Users\aqeed\OneDrive - Rainboweucalyptus Technologies Private Limited\R&D Efficiency\ELN Intelligence Platform\`

2. When starting a Claude Code session, say:
   > *"Read ELN_PLATFORM_CONTEXT.md first, then [describe your change]"*

3. Claude Code will read the file, understand the full platform, and make changes correctly without you re-explaining context.

---

## Platform Overview

**Company:** Covvalent (Rainboweucalyptus Technologies Pvt. Ltd.) — specialty chemicals CDMO
**Platform:** ELN Intelligence Platform — AI-augmented R&D operations console
**Status:** Live in production as of June 2026
**Users:** @covvalent.com Microsoft accounts only (Entra ID enforced)

### What it does
Ingests R&D experiment data from DIMA ELN (SQL Server on ELL-VM) → ELNAnalytics DB → FastAPI backend → React dashboard with AI chat agent grounded in 1,709 internal experiments.

---

## Azure Subscriptions

| Name | ID | Purpose |
|---|---|---|
| Nexus credits | `9e25d11c-3753-4b8c-a575-0bcc44f964d4` | ALL platform resources |
| Subscription A | `b10caf33-c875-4c96-9d7d-1b211acd0ac4` | ELL-VM only (cannot migrate — Savings Plan bound) |
| Tenant | `b0d15824-98fa-4de2-9b20-bd4f0ed01352` | Rainboweucalyptus Technologies |

**Always set subscription before any CLI commands:**
```bash
az account set --subscription 9e25d11c-3753-4b8c-a575-0bcc44f964d4  # platform
az account set --subscription b10caf33-c875-4c96-9d7d-1b211acd0ac4  # ELL-VM
```

---

## Live URLs

| Component | URL |
|---|---|
| Dashboard (SWA) | https://zealous-field-085c0ae00.7.azurestaticapps.net |
| FastAPI | https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net |
| API health | .../health |
| API SQL check | .../health/sql |
| AI Foundry | https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project |

---

## Architecture

```
React Dashboard (SWA)
    ↓ SWA built-in Entra ID auth (no MSAL in React)
    ↓ /.auth/me for user info
FastAPI v2.3.0 (App Service B1, South India)
    ├── GET  /api/projects
    ├── GET  /api/experiments
    ├── GET  /api/dashboard/summary      ← live stats from SQL
    ├── GET  /api/dashboard/efficiency   ← 3-period snapshots from SQL
    ├── GET  /api/search                 ← hybrid BM25+vector+semantic (AI Search)
    ├── POST /api/ai/fetch               ← structured SQL retrieval (Tool 1)
    ├── POST /api/ai/chat                ← agent tool-call loop (gpt-5.4)
    └── GET  /api/ai/literature          ← PubChem + CrossRef (Tool 3)
        ↓ VNet integration
ELL-VM (SQL Server 2019 Express, 10.0.0.4,1433)
    └── ELNAnalytics DB ← nightly ETL from Condor + Atlas
AI Search (Central India, Basic)
    └── eln-experiments index, 4,954 chunks, 1,709 experiments
AI Foundry (South India)
    └── Agent: asst_iujfiErrYF9CfqgyB6BqY4Xn (gpt-5.4, system_prompt_v4)
```

---

## Source File Structure

```
ELN Intelligence Platform/
├── ELN_PLATFORM_CONTEXT.md        ← this file
├── eln-api/                        ← FastAPI backend
│   ├── main.py                     ← all REST endpoints
│   ├── requirements.txt
│   ├── startup.sh
│   ├── .ostype                     ← LINUX
│   └── routers/
│       ├── __init__.py
│       ├── agent.py                ← POST /api/ai/chat
│       ├── fetch.py                ← POST /api/ai/fetch (Tool 1)
│       ├── search.py               ← GET /api/search (Tool 2)
│       └── literature.py           ← GET /api/ai/literature (Tool 3)
└── eln-dashboard/                  ← React frontend
    ├── package.json
    ├── public/
    │   ├── index.html
    │   └── staticwebapp.config.json  ← AAD auth enforcement
    └── src/
        ├── index.js
        ├── App.js                  ← full dashboard UI
        └── AIChatPanel.js          ← floating chat panel
```

---

## ELNAnalytics Database Schema

**Connection:** `SERVER=10.0.0.4,1433` (always explicit TCP port, never named instance)
**Database:** `ELNAnalytics` | **User:** `eln_reader`

### Key tables and EXACT column names

#### eln_projects
| Column | Type | Notes |
|---|---|---|
| `project_id` | int | PK |
| `project_code` | varchar | e.g. P013E00 |
| `title` | varchar | Project/product name (NOT project_title) |
| `cas_number` | varchar | |
| `generic_name` | varchar | |
| `iupac_name` | varchar | |
| `project_status` | tinyint | 1=Active |
| `start_date` | date | |

#### eln_project_teams
| Column | Type |
|---|---|
| `project_team_id` | int PK |
| `project_id` | int FK → eln_projects |

#### eln_experiments
| Column | Type | Notes |
|---|---|---|
| `experiment_id` | int | PK |
| `project_team_id` | int | FK → eln_project_teams |
| `exp_number_full` | varchar | Computed: `R&D/P013E00/2606/375` |
| `experiment_number` | int | Sequence number only |
| `prefix` | varchar | e.g. `R&D/P013E00/2606` |
| `title` | varchar | Experiment title (NOT experiment_title) |
| `objective` | nvarchar | |
| `conclusion` | nvarchar | |
| `next_action_plan` | nvarchar | |
| `experiment_status` | tinyint | 1=Active, 2=Done |
| `created_date` | datetime | Use for ALL date filtering (NOT last_modified_date) |
| `author` | nvarchar | Backfilled nightly at 02:15 IST by ELN_Patch_Author task |

#### eln_experiment_materials
| Column | Type | Notes |
|---|---|---|
| `raw_material_id` | int PK | |
| `experiment_id` | int FK | |
| `raw_material_name` | nvarchar | (NOT material_name) |
| `cas_number` | nvarchar | |
| `quantity` | decimal | |
| `unit` | tinyint | |
| `moles` | decimal | |
| `ratio` | float | (NOT molar_ratio) |
| `is_limiting_agent` | bit | KSM flag (NOT is_ksm) |

#### eln_experiment_products
| Column | Type | Notes |
|---|---|---|
| `reaction_product_id` | int PK | |
| `experiment_id` | int FK | |
| `product_name` | varchar | |
| `dry_wt` | decimal | (NOT dry_weight) |
| `crude_yield` | float | |
| `purified_yield` | float | |
| `purity` | float | |
| `atom_economy` | float | |
| `e_factor_actual` | float | (NOT e_factor) |

#### eln_experiment_procedure
| Column | Type | Notes |
|---|---|---|
| `procedure_row_id` | int PK | |
| `experiment_id` | int FK | |
| `step_order` | int | (NOT step_number) |
| `operation` | nvarchar | |
| `observations` | nvarchar | (NOT description) |
| `temperature` | nvarchar | |
| `time_value` | nvarchar | |
| `quantity` | nvarchar | |
| `is_header` | bit | Filter WHERE is_header = 0 |

#### eln_experiment_tlc
| Column | Type | Notes |
|---|---|---|
| `tlc_plate_id` | int PK | |
| `experiment_id` | int FK | |
| `plate_title` | varchar | |
| `plate_notes` | varchar | |
| `spot_a_notes` | varchar | |
| `rf1` | varchar | Rf for spot A |
| `spot_b_notes` | varchar | |
| `rf2` | varchar | Rf for spot B |
| `spot_c_notes` | varchar | |
| `rf3` | varchar | Rf for spot C |
| `spot_d_notes` | varchar | |
| `rf4` | varchar | Rf for spot D |

#### AI Search index (eln-experiments)
Key field names (different from SQL):
| Index field | Notes |
|---|---|
| `chunk_id` | PK (NOT id) |
| `text` | Content field (NOT content) |
| `experiment_title` | Title in index (NOT title) |
| `scientist` | Author in index (NOT author) |
| `@search.reranker_score` | NOT selectable in $select — returned automatically |

---

## FastAPI Routers — Key Details

### POST /api/ai/fetch (fetch.py)
Accepts JSON body with ANY combination:
```json
{}                                    // All projects list
{"project_code": "P013E00"}           // Project + up to 50 recent experiments
{"experiment_id": 566}                // Full detail
{"exp_number_full": "R&D/..."}        // Full detail by number
{"days": 7}                           // Last 7 days all projects
{"days": 7, "project_code": "P013E00"} // Last 7 days specific project
{"cas_number": "41340-36-7"}          // Find by CAS
{"product_name": "tryptophan"}        // Fuzzy name search
{"chemistry": "fluorination"}         // Chemistry class search
{"chemistry": "Grignard", "project_code": "P100P02"}
{"chemistry": "acetylation", "days": 30}
```
Project drill-down returns max `limit` (default 50) most recent experiments.

### POST /api/ai/chat (agent.py)
- Agent ID: `asst_iujfiErrYF9CfqgyB6BqY4Xn`
- Model: `gpt-5-4` (gpt-5.4 deployment on aifoundry-eln-covvalent)
- Poll interval: 0.8s
- Max completion tokens: 16,384
- Timeout: 120s
- `FOUNDRY_ENDPOINT` app setting contains full project path — do NOT append `/api/projects/eln-agent-project` again in code

### GET /api/search (search.py)
- Uses `VectorizableTextQuery` (NOT `VectorizedQuery`)
- Select fields: `chunk_id`, `exp_number_full`, `chunk_type`, `experiment_id`, `project_code`, `experiment_title`, `scientist`, `text`
- Do NOT include `@search.reranker_score` in select list

---

## Frontend — Key Details

### Brand Colors (Covvalent)
```javascript
const C = {
  navy:  '#000B36',  // sidebar bg, headings, table headers
  blue:  '#0E2673',  // body text, buttons, borders
  cyan:  '#9DD1F1',  // accent, active states, sidebar text
  ice:   '#DEEBF7',  // card/row backgrounds, borders
  white: '#FFFFFF',  // page background
}
```
Font: **Inter** (Google Fonts). Never use generic grays, reds, purples, or any color outside the 5 above.

### Authentication
- SWA Standard SKU, built-in Entra ID provider
- **NO MSAL in React** — SWA handles auth server-side
- User info: `fetch('/.auth/me')` → `data.clientPrincipal`
- `staticwebapp.config.json` must be in `public/` for auth enforcement
- **SWA identity.7 bug (Apr 2026):** custom AAD auth block causes `clientPrincipal` to return null — always use built-in pre-configured provider, never add custom `auth` block

### Chat Panel (AIChatPanel.js)
- sessionStorage persistence: `eln_chat_messages`, `eln_chat_thread_id`
- CSV download triggers automatically when agent returns a markdown table
- Typing indicator with stage progression: thinking → fetching → searching → writing

### Deploy commands (Cloud Shell)
```bash
# API
cd ~/eln-api
zip -r ~/eln-api-clean.zip . --exclude "antenv/*"
az webapp deploy --name eln-api-covvalent --resource-group rg-eln-covvalent --src-path ~/eln-api-clean.zip --type zip --async true

# Dashboard
cd ~/eln-dashboard
REACT_APP_API_URL=https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net npm run build
SWA_TOKEN=$(az staticwebapp secrets list --name eln-dashboard-covvalent --query 'properties.apiKey' -o tsv)
npx @azure/static-web-apps-cli@1.1.7 deploy ./build --deployment-token "$SWA_TOKEN" --env production
```

---

## AI Agent — System Prompt v4

The agent (`asst_iujfiErrYF9CfqgyB6BqY4Xn`) uses system_prompt_v4 incorporating:
- **chemist-analyst skill:** mechanism reasoning, CPP analysis, route/selectivity scoring, 14-section compound profile
- **rnd-meeting-copilot-v2 skill:** senior chemist persona, priority-ordered experiment queue, stop/proceed/branch rules, hypothesis validation
- **experimental-review-design skill:** gaps → review → conclusion → next experiments structure

Key tool routing rules in the system prompt:
- **Date queries** → always `fetch_experiment` with `days` param, NEVER `search_experiments`
- **Chemistry class queries** → `fetch_experiment` with `chemistry` param first, then fetch detail, then `search_literature`
- **Project identity** → always open with `**[Code] — [Name] (CAS [number])**`

**To patch the agent system prompt:**
```bash
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
curl -s -X POST \
  "https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project/assistants/asst_iujfiErrYF9CfqgyB6BqY4Xn?api-version=2025-05-15-preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @/home/aqeedat/system_prompt_patch.json | grep -E '"id"|"model"'
```

---

## Nightly Pipeline

```
02:00 AM IST  ELN_ETL_NightlySync       SQL ETL: Condor+Atlas → ELNAnalytics
02:15 AM IST  ELN_Patch_Author          Backfill author field from Atlas CreatedBy
02:30 AM IST  ELN_Export_ToBlob         7 tables → stelncoovalent/eln-analytics/ (CSVs)
03:00 AM IST  logic-eln-indexer-schedule ACI container: CSVs → embed → upsert to AI Search
```

---

## Azure Resources (nexus subscription, rg-eln-covvalent)

| Resource | Name | Cost | Notes |
|---|---|---|---|
| App Service B1 | eln-api-covvalent | ~$13/mo | FastAPI, South India |
| Static Web App | eln-dashboard-covvalent | ~$9/mo | Standard SKU for auth |
| AI Search Basic | aisrch-eln-covvalent | ~$75/mo | Central India (South India lacks semantic ranker) |
| AI Foundry | aifoundry-eln-covvalent | $0 base | South India, tokens via AOAI |
| Azure OpenAI | aoai-eln-covvalent | pay/token | gpt-4o + text-embedding-3-large |
| Storage GPv1 | stelncoovalent | ~$1-2/mo | **Migrate to GPv2 before Oct 2026** |
| Logic App + ACI | logic-eln-indexer | ~$1-3/mo | Nightly indexer |
| Key Vault | kv-eln-covvalent | <$1/mo | RBAC-enabled |
| App Insights | appi-eln-covvalent | <$1/mo | InstrumentationKey: dd13a538 |

**AI deployments on aifoundry-eln-covvalent:**
- `gpt-5-4` — gpt-5.4 (2026-03-05), GlobalStandard, 30K TPM — used by agent
- `gpt-4o` — kept as fallback
- `text-embedding-3-large` — 10K TPM, used by AI Search vectorizer

---

## Key People

| Name | Role | Contact |
|---|---|---|
| Aqeedat Kaur Sandhu | Tech Lead | aqeedat.kaur.sandhu@covvalent.com |
| Dr. Rahul Saxena | Chief Scientific Officer, AIE-301 reviewer | — |
| Sandeep Singh | Co-Founder / Global Admin (AAD consent authority) | — |
| Arush Dhawan | Co-Founder / Global Admin | — |
| Ea Takano | MfS Startup Advisor | v-ietaka@microsoft.com |
| DIMA Support | ELN vendor (must be notified on ellman password rotation) | techsupport@dugroup.in |

---

## Critical Rules — Hard-Won

| Rule | Detail |
|---|---|
| SQL connection | `SERVER=10.0.0.4,1433` — always explicit TCP port, never named instance remotely |
| SQL from VM | `localhost\SQLEXPRESS` — IP path fails from Local System context |
| Column names | `title` not `experiment_title`, `raw_material_name` not `material_name`, `dry_wt` not `dry_weight`, `e_factor_actual` not `e_factor`, `step_order` not `step_number`, `observations` not `description`, `created_date` not `last_modified_date` |
| PK names | `project_id` not `id`, `experiment_id` not `id`, `project_team_id` not `id` |
| FOUNDRY_ENDPOINT | Already includes `/api/projects/eln-agent-project` — never append it again in code |
| VectorizableTextQuery | Use this (not VectorizedQuery) for AI Search hybrid search |
| @search.reranker_score | Never include in $select — it's an annotation returned automatically |
| SWA auth | Never add custom `auth` block — use built-in pre-configured Entra ID only (identity.7 bug) |
| az webapp deploy | Always use `--async true` — synchronous polling causes Cloud Shell disconnection |
| WEBSITE_CONTENTOVERVNET=1 | Never add to Function Apps — kills Python worker silently |
| Key Vault | RBAC-enabled — use `az role assignment create`, never `az keyvault set-policy` |
| Cloud Shell | Resets between sessions — all files and env vars lost. Source of truth = OneDrive folder |
| DIMA password | Notify techsupport@dugroup.in whenever ellman password rotates — they reconnect VPN |
| aiohttp | Must be in requirements.txt — azure-identity async needs it |

---

## Pending Items

| Item | Priority | Deadline |
|---|---|---|
| Dr. Saxena AIE-301 formal sign-off | High | Before R&D team rollout |
| Assistants API migration to new Agents Service | Critical | **Aug 26, 2026** |
| GPv1 → GPv2 storage migration (stelncoovalent) | High | **Oct 13, 2026** |
| Delete rsv-eln-covvalent (empty vault) | Low | Anytime |
| Delete snet-aca-eln + snet-aci-eln (orphaned subnets) | Low | Anytime |
| Delete func-eln-ingest (deprecated) | Low | Anytime |

---

## Cloud Shell Session Restore

Run at the start of every Cloud Shell session:
```bash
az login --identity
az account set --subscription 9e25d11c-3753-4b8c-a575-0bcc44f964d4

# Smoke tests
curl -s https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net/health
curl -s https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net/api/dashboard/summary | python3 -m json.tool

# Verify agent model
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
curl -s "https://aifoundry-eln-covvalent.services.ai.azure.com/api/projects/eln-agent-project/assistants/asst_iujfiErrYF9CfqgyB6BqY4Xn?api-version=2025-05-15-preview" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep '"model"'
```

---

## Self-Update Instructions for Claude Code

**Claude Code must update this file automatically at the end of every session** where any of the following changed:

- A new API endpoint was added or modified
- A column name was corrected or a new table was discovered
- A new Azure resource was created or deleted
- An app setting was changed (model name, API version, endpoint URL)
- A bug was fixed that revealed a constraint or rule (new "hard-won" rule)
- A pending item was completed or a new one was added
- Brand/UI changes were made (colors, component structure)
- The agent system prompt was patched

### How to update

At the end of the session, Claude Code should say:
> *"The following changes were made this session — updating ELN_PLATFORM_CONTEXT.md:"*
> - [list each change]

Then edit the relevant sections directly:
- Update `Last updated:` date at the top
- Correct column names / add new tables in the Schema section
- Update Source File Structure if files were added or removed
- Update Pending Items — mark completed items ✅ Done, add new ones
- Add new hard-won rules to Critical Rules table
- Update Azure Resources if deployments changed

### What NOT to update
- Do not remove historical hard-won rules — keep them even if resolved
- Do not rewrite large sections speculatively — only update what changed this session
- Do not update if nothing changed

### Trigger phrase for manual update
> *"Update ELN_PLATFORM_CONTEXT.md with what changed today"*

### What changed in the 24 June 2026 session
- gpt-5.4 deployed on `aifoundry-eln-covvalent` as deployment `gpt-5-4`
- Agent patched from gpt-4o to gpt-5-4
- `aiohttp==3.9.5` added to requirements.txt (azure-identity async dependency)
- `max_completion_tokens` raised from 4096 to 16384 in agent.py
- `FOUNDRY_ENDPOINT` base_url duplication bug fixed in agent.py
- `VectorizableTextQuery` replaced `VectorizedQuery` in search.py
- `@search.reranker_score` removed from $select in search.py
- `fetch.py` extended with 7 query modes: empty, project, experiment, days, cas_number, product_name, chemistry
- Project drill-down limited to `FETCH NEXT ? ROWS ONLY` (default 50) to prevent token overflow
- `main.py` rebuilt with correct column names from INFORMATION_SCHEMA inspection
- `App.js` rebuilt with Covvalent brand colors (navy/blue/cyan/ice)
- System prompt upgraded to v4: full chemist-analyst + rnd-meeting-copilot-v2 + experimental-review-design + tool routing rules
- `staticwebapp.config.json` added to `public/` for AAD auth enforcement
- `GET /api/dev/schema/{table}` endpoint added to main.py for schema inspection
