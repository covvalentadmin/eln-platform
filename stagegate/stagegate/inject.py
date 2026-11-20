"""`stagegate inject`: push a fixture's G1 checklist into the SG-TEST Clappia apps.

Order: Project Master (match project_code; create if missing, NEVER edited once it exists: people own
its people_fields, status owns its system_fields) -> Gate Items (create only missing idempotency_keys)
-> G1 Gate Decision (create if missing). Safe to re-run.

--dry-run makes NO network calls at all (not even reads): it shows what a run against
empty apps would create. Live runs need SG_ENABLED=true, CLAPPIA_API_KEY and CLAPPIA_USER_EMAIL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Optional

from stagegate.clappia import (DEFAULT_DOTENV, ClappiaClient, ClappiaError, Config, fv, load_dotenv,
                               same_value)
from stagegate.engine import build_checklist, load_library, routing_fields
from stagegate.pilot import planned_violations, refuse

TEST_PREFIX = "FX-"
GATE = "G1"

EXIT_OK, EXIT_ERRORS, EXIT_REFUSED = 0, 1, 2


class Summary:
    def __init__(self):
        self.rows = []  # (status, target, detail)

    def add(self, status: str, target: str, detail: str = ""):
        self.rows.append((status, target, detail))

    def count(self, status: str) -> int:
        return sum(1 for s, _, _ in self.rows if s == status)

    def render(self, out, dry_run: bool):
        for s, t, d in self.rows:
            if s == "kept":
                print(f"  kept Clappia value: {t}", file=out)
                continue
            print(f"  {s:12} {t}" + (f"  -- {d}" if d else ""), file=out)
        keys = ["would create", "would upsert"] if dry_run else ["created", "updated", "skipped", "error", "kept"]
        totals = ", ".join(f"{k}={self.count(k)}" for k in keys)
        print(f"\nsummary{' (DRY RUN, no API calls made)' if dry_run else ''}: {totals}", file=out)


def clappia_project_fields(project: dict, settings: dict) -> dict:
    """The fixture project fields inject may send to the Projects app: people_fields only, in fixture
    order. Routing-only fields (sponsor_email, rd_chemists, ...) and system_fields are never sent."""
    people = set(settings.get("people_fields") or ())
    return {k: v for k, v in project.items() if k in people}


def unknown_project_fields(project: dict, settings: dict) -> list:
    """Fixture project keys in none of people_fields, system_fields or role_routing."""
    known = (set(settings.get("people_fields") or ()) | set(settings.get("system_fields") or ())
             | routing_fields(settings))
    return [k for k in project if k not in known]


def gate_decision_record(project: dict) -> dict:
    return {"project_code": project["project_code"], "gate": GATE,
            "receiving_poc_email": project.get("rd_lead_email", "")}


def _changed(existing: dict, wanted: dict) -> dict:
    """Fields of `wanted` (payload form) that differ from `existing` (raw or fv()-normalised Clappia
    values). Multi-select lists compare order-insensitively (clappia.same_value)."""
    return {k: v for k, v in wanted.items() if not same_value(existing.get(k), v)}


def to_payload(data: dict, select_fields) -> dict:
    """Clappia write format, applied to every create/edit body:
    empty (None / "") dropped; Select -> [str(v)]; lists unchanged; everything else -> str(v)."""
    sel = set(select_fields or ())
    out = {}
    for k, v in data.items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            out[k] = v
        elif k in sel:
            out[k] = [str(v)]
        else:
            out[k] = str(v)
    return out


def load_config(env: Optional[dict], dotenv_path: Optional[Path]) -> Config:
    """env=None: real environment plus .env (tests pass an explicit dict and never touch .env)."""
    if env is None:
        load_dotenv(dotenv_path)
        return Config.from_env()
    return Config.from_env(env)


def guard_enabled(cfg: Config, cmd: str, out) -> bool:
    if not cfg.enabled:
        print(f"SG_ENABLED is not 'true'; {cmd} disabled. Nothing done.", file=out)
        return False
    return True


def guard_project(pc: str, allow_live: bool, out) -> bool:
    if not pc.startswith(TEST_PREFIX) and not allow_live:
        print(f"Refusing project_code {pc!r}: not a {TEST_PREFIX}* test project. Pass --allow-live to override.",
              file=out)
        return False
    return True


def run_inject(fixture: str, dry_run: bool = False, allow_live: bool = False,
               env: Optional[dict] = None, dotenv_path: Optional[Path] = DEFAULT_DOTENV,
               client_factory: Callable[[Config], ClappiaClient] = ClappiaClient,
               out=sys.stdout) -> int:
    cfg = load_config(env, dotenv_path)
    if not guard_enabled(cfg, "inject", out):
        return EXIT_REFUSED

    data = json.load(open(fixture, encoding="utf-8"))
    project, sidecar = data["project"], data["sidecar"]
    pc = project.get("project_code") or sidecar.get("project_code") or ""
    if not guard_project(pc, allow_live, out):
        return EXIT_REFUSED

    lib = load_library()
    items, log = build_checklist(project, sidecar, lib)
    sel = lib.settings.get("select_fields") or {}
    sel_pm, sel_gi, sel_gd = (sel.get(k) for k in ("project_master", "gate_items", "gate_decision"))
    decision = gate_decision_record(project)
    unknown = unknown_project_fields(project, lib.settings)
    if unknown:
        print(f"inject refused: fixture project field(s) {unknown} are not in settings.yaml people_fields, "
              "system_fields or role_routing. Nothing sent.", file=out)
        return EXIT_REFUSED
    project_out = clappia_project_fields(project, lib.settings)
    # Pilot guard: before any output, dry run or API call. No partial writes.
    violations = planned_violations(pc, project_out, items, decision, GATE, lib.settings)
    if violations:
        refuse("inject", violations, out)
        return EXIT_REFUSED
    summ = Summary()
    print(f"inject {pc}: {len(items)} checklist items, import log {json.dumps(log)}", file=out)
    print(f"apps: project_master={cfg.app_project_master} gate_items={cfg.app_gate_items} "
          f"gate_decision={cfg.app_gate_decision} workplace={cfg.workplace_id}\n", file=out)

    if dry_run:
        summ.add("would upsert", f"Project Master {pc}", f"{len(project_out)} fields, match on project_code")
        for it in items:
            summ.add("would create", f"Gate Item {it.idempotency_key}", f"{it.item_class}"
                     + (", HARD STOP" if it.hard_stop else ""))
        summ.add("would create", f"Gate Decision {pc}|{GATE}",
                 f"receiving_poc_email={decision['receiving_poc_email']}")
        summ.render(out, dry_run=True)
        return EXIT_OK

    missing = cfg.missing_for_live()
    if missing:
        print(f"Missing config for a live run: {', '.join(missing)}. Nothing done.", file=out)
        return EXIT_REFUSED
    client = client_factory(cfg)

    # 1. Project Master. If we can't read it, stop: everything downstream keys off it.
    #    Missing -> create with the fixture's people_fields. Existing -> NEVER edited: people own those
    #    fields once the record exists, and system_fields belong to status. Differences are reported only.
    try:
        found = client.get_submissions(cfg.app_project_master, {"project_code": pc})
        if len(found) > 1:
            raise ClappiaError(f"{len(found)} Project Master records for {pc}; fix duplicates by hand")
        pm_payload = to_payload(project_out, sel_pm)
        if not found:
            sid = client.create_submission(cfg.app_project_master, pm_payload)
            summ.add("created", f"Project Master {pc}", sid)
        else:
            sid = found[0].get("submissionId", "")
            # Compared in payload form, so values the fixture leaves empty are never reported; against the
            # raw record, so a multi-select with the same options in another order is not a difference.
            kept = list(_changed(found[0].get("submissionFieldValues") or {}, pm_payload))
            summ.add("skipped", f"Project Master {pc}",
                     f"{sid} unchanged" if not kept else f"{sid} exists; Clappia values kept, nothing sent")
            for f in kept:
                summ.add("kept", f)
    except ClappiaError as ex:
        summ.add("error", f"Project Master {pc}", str(ex))
        print("Aborting: Project Master step failed.", file=out)
        summ.render(out, dry_run=False)
        return EXIT_ERRORS

    # 2. Gate Items: no read, no writes (otherwise we can't guarantee idempotency).
    try:
        existing = {fv(s).get("idempotency_key") for s in client.get_submissions(cfg.app_gate_items,
                                                                                 {"project_code": pc})}
    except ClappiaError as ex:
        summ.add("error", f"Gate Items {pc}", f"could not read existing items, none created: {ex}")
        existing = None
    if existing is not None:
        for it in items:
            key = it.idempotency_key
            if key in existing:
                summ.add("skipped", f"Gate Item {key}", "already exists")
                continue
            try:
                sid = client.create_submission(cfg.app_gate_items, to_payload(it.to_clappia(), sel_gi))
                existing.add(key)
                summ.add("created", f"Gate Item {key}", sid)
            except ClappiaError as ex:
                summ.add("error", f"Gate Item {key}", str(ex))

    # 3. G1 Gate Decision
    target = f"Gate Decision {pc}|{GATE}"
    try:
        # Server filter on project_code (text) only; gate is a Select field, so match it client-side.
        found = [s for s in client.get_submissions(cfg.app_gate_decision, {"project_code": pc})
                 if fv(s).get("gate", "") == GATE]
        if found:
            summ.add("skipped", target, f"{found[0].get('submissionId', '')} already exists")
        else:
            summ.add("created", target, client.create_submission(cfg.app_gate_decision,
                                                                 to_payload(decision, sel_gd)))
    except ClappiaError as ex:
        summ.add("error", target, str(ex))

    summ.render(out, dry_run=False)
    return EXIT_ERRORS if summ.count("error") else EXIT_OK
