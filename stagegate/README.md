# stagegate — Stage-gate MVP v0.1 (G1 only)

TEST — not a gate decision. Builds G1 checklists from the kickoff register and writes them to the `SG-TEST ·` Clappia apps.
Branch: `feature/stage-gate`. No Azure, no ELN, no SharePoint integration in v0.1.

## Layout
| Path | What |
|---|---|
| `data/g1_core.yaml` | G1-01..G1-13, verbatim from spec |
| `data/flag_rules_g1.yaml` | 15 G1 flag rules (DF-S1/S2/S5, R1/R2/R3/R5/R11, G1/G2/G6/G7, L2/L5/L7) |
| `data/learning_map_deferred.yaml` | Learning IDs for G2–G4 rules not loaded yet; rows land at the right gate, never dropped |
| `data/settings.yaml` | Role → Project Master field map, fallbacks, G1-11 class (open decision #3) |
| `schema/kickoff_sidecar.schema.json` | Sidecar contract (5 register fields **assumed**: risk, score, confidence, evidence, learning_id) |
| `stagegate/engine.py` | Pure classifier: `build_checklist(project, sidecar, lib) -> (items, log)` |
| `stagegate/readiness.py` | Traffic light + gate-ready from Gate Items records |
| `stagegate/cli.py` | `preview`, `inject`; `status` (Day 4) |
| `stagegate/clappia.py` | Thin stdlib client: create / edit / getSubmissions (`x-api-key` auth), tiny `.env` loader |
| `stagegate/inject.py` | Idempotent write: Project Master upsert → missing Gate Items → G1 Gate Decision |
| `fixtures/FX-{1,2,3}.json` | Clean / hazardous / blocked; role holders = pilot users |

## Run
```
pip install -r requirements.txt
python -m pytest -q
python -m stagegate.cli preview fixtures/FX-2.json
python -m stagegate.cli inject fixtures/FX-1.json --dry-run   # no API calls at all
```

`inject` exits unless `SG_ENABLED=true`, and refuses non-`FX-` project codes without `--allow-live`.
A live run needs `CLAPPIA_API_KEY` and `CLAPPIA_USER_EMAIL` in `.env`. Re-runs are safe: Gate Items
are matched on `idempotency_key`, and the Gate Decision on `project_code` + `gate`.

## Classification (spec)
| Input | Class | Gate |
|---|---|---|
| Score 5 | Critical, hard stop | Always G1 |
| Score 4 | Critical | Rule's target gate |
| Score 3 | Note | Rule's target gate |
| Score 1–2 | Skipped (logged) | — |
| learning_match | Raises Note → Critical | — |
| Mandatory breach / info | Critical / Note | Rule's gate |
| No rule match | Generic item, class by score | G1 (or deferred rule's gate) |

Merges on `(gate, item_id)` raise class only; nothing lowers a class.
