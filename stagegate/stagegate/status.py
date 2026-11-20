"""`stagegate status`: compute the G1 traffic light from live Gate Items and write it back.

Reads (per project): Project Master, all Gate Items, the G1 Gate Decision.
Gate Items' `item_status` is the Clappia formula's output and is used as is (never re-derived).
readiness.evaluate() gives Red / Amber / Ready; the Gate Decision then turns Ready into:
  Green  if gate_decision == "Pass" and ownership_accepted == "Accepted"
  Amber  otherwise, blockers "Ready - awaiting Pass + ownership"
Writes only fields that changed; the timestamp fields are added only alongside a real change.

--dry-run makes NO network calls: it evaluates the fixture's checklist as freshly injected
(every item open, no decision yet) and shows what would be written.

Pilot guard (settings enforce_pilot_allowlist): with a fixture, the fixture's emails are checked
before any API call; with --project, the emails in the records read are checked before any write.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from stagegate.clappia import DEFAULT_DOTENV, ClappiaClient, ClappiaError, Config, fv, norm_value
from stagegate.engine import SettingsError, build_checklist, load_library
from stagegate.inject import (EXIT_ERRORS, EXIT_OK, EXIT_REFUSED, GATE, _changed, clappia_project_fields,
                              gate_decision_record, guard_enabled, guard_project, load_config, to_payload)
from stagegate.pilot import planned_violations, record_violations, refuse
from stagegate.readiness import evaluate

AWAITING = "Ready - awaiting Pass + ownership"
# Every field status may write to the Projects record. Must be a subset of settings system_fields.
PROJECT_FIELDS_WRITTEN = ("traffic_light", "open_critical", "open_standard", "unacked_notes", "last_engine_run")


def check_system_fields(fields, settings: dict) -> None:
    """Raise unless every Projects field status would write is in settings.yaml system_fields."""
    outside = sorted(set(fields) - set(settings.get("system_fields") or ()))
    if outside:
        raise SettingsError(f"status would write Projects field(s) {outside} that are not in "
                            "settings.yaml system_fields")


def final_light(ev: dict, decision: dict) -> tuple:
    """(traffic_light, blockers) from evaluate() output and the normalised G1 Gate Decision."""
    if ev["traffic_light"] in ("Red", "Amber"):
        return ev["traffic_light"], ev["blockers"]
    if decision.get("gate_decision") == "Pass" and decision.get("ownership_accepted") == "Accepted":
        return "Green", ev["blockers"]
    return "Amber", AWAITING


def utc_stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _report(out, pc, light, ev, blockers, edits, errors, dry_run=False):
    print(f"status {pc} {GATE}: {light}", file=out)
    print(f"  counts:   open_critical={ev['open_critical']}, open_standard={ev['open_standard']}, "
          f"unacked_notes={ev['unacked_notes']}", file=out)
    print(f"  blockers: {blockers}", file=out)
    print(f"  {'would write' if dry_run else 'edits'}:", file=out)
    for target, diff in edits:
        if diff:
            shown = ", ".join(f"{k}={norm_value(v)}" for k, v in diff.items())
            print(f"    {target}: {shown}", file=out)
        else:
            print(f"    {target}: no change", file=out)
    for e in errors:
        print(f"  error: {e}", file=out)
    if dry_run:
        print("\nDRY RUN, no API calls made (simulated: all items open, no Gate Decision values)", file=out)


def run_status(fixture: Optional[str] = None, project: Optional[str] = None, dry_run: bool = False,
               allow_live: bool = False, env: Optional[dict] = None,
               dotenv_path: Optional[Path] = DEFAULT_DOTENV,
               client_factory: Callable[[Config], ClappiaClient] = ClappiaClient,
               out=sys.stdout, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> int:
    cfg = load_config(env, dotenv_path)
    if not guard_enabled(cfg, "status", out):
        return EXIT_REFUSED

    data = None
    if fixture:
        data = json.load(open(fixture, encoding="utf-8"))
        pc = data["project"].get("project_code") or data["sidecar"].get("project_code") or ""
    else:
        pc = project or ""
    if not guard_project(pc, allow_live, out):
        return EXIT_REFUSED

    lib = load_library()
    check_system_fields(PROJECT_FIELDS_WRITTEN, lib.settings)  # before any API call
    sel = lib.settings.get("select_fields") or {}
    sel_pm, sel_gd = sel.get("project_master"), sel.get("gate_decision")

    # Pilot guard, fixture mode: the same check as inject, before any API call (live or dry run).
    fixture_items = None
    if data is not None:
        fixture_items, _ = build_checklist(data["project"], data["sidecar"], lib)
        violations = planned_violations(pc, clappia_project_fields(data["project"], lib.settings), fixture_items,
                                        gate_decision_record(data["project"]), GATE, lib.settings)
        if violations:
            refuse("status", violations, out)
            return EXIT_REFUSED

    def pm_fields(light, ev):
        return to_payload({"traffic_light": light, "open_critical": ev["open_critical"],
                           "open_standard": ev["open_standard"], "unacked_notes": ev["unacked_notes"]}, sel_pm)

    def gd_fields(ev, blockers):
        return to_payload({"gate_ready": ev["gate_ready"], "blockers": blockers}, sel_gd)

    if dry_run:
        if data is None:
            print("--dry-run makes no API calls, so it needs a fixture to simulate; "
                  "--project needs a live read.", file=out)
            return EXIT_REFUSED
        records = [{k: norm_value(v) for k, v in it.to_clappia().items()} for it in fixture_items]
        ev = evaluate(records, GATE)
        light, blockers = final_light(ev, {})
        ts = utc_stamp(now())
        _report(out, pc, light, ev, blockers,
                [("Project Master", {**pm_fields(light, ev), "last_engine_run": ts}),
                 (f"Gate Decision {GATE}", {**gd_fields(ev, blockers), "readiness_checked_at": ts})],
                [], dry_run=True)
        return EXIT_OK

    missing = cfg.missing_for_live()
    if missing:
        print(f"Missing config for a live run: {', '.join(missing)}. Nothing done.", file=out)
        return EXIT_REFUSED
    client = client_factory(cfg)
    errors, edits = [], []

    # Reads. Gate Items and the Gate Decision decide the light, so failing either aborts.
    try:
        pms = client.get_submissions(cfg.app_project_master, {"project_code": pc})
        records = [fv(s) for s in client.get_submissions(cfg.app_gate_items, {"project_code": pc})]
        decisions = [s for s in client.get_submissions(cfg.app_gate_decision, {"project_code": pc})
                     if fv(s).get("gate", "") == GATE]
    except ClappiaError as ex:
        print(f"status {pc}: read failed, nothing written: {ex}", file=out)
        return EXIT_ERRORS
    if not records:
        print(f"status {pc}: no Gate Items found; run inject first. Nothing written.", file=out)
        return EXIT_ERRORS
    if data is None:
        # Pilot guard, --project mode: no local data, so check what was read, before any write.
        violations = record_violations(pc, [fv(s) for s in pms], records, [fv(s) for s in decisions],
                                       GATE, lib.settings)
        if violations:
            refuse("status", violations, out, nothing="Nothing written")
            return EXIT_REFUSED

    decision = {}
    if len(decisions) == 1:
        decision = fv(decisions[0])
    elif not decisions:
        errors.append(f"no {GATE} Gate Decision for {pc}; run inject first (light cannot be Green)")
    else:
        errors.append(f"{len(decisions)} {GATE} Gate Decisions for {pc}; fix duplicates by hand "
                      "(none used, none written)")

    ev = evaluate(records, GATE)
    light, blockers = final_light(ev, decision)
    ts = utc_stamp(now())

    def write(app, rec, wanted, stamp_field, label):
        sid = rec.get("submissionId", "")
        diff = _changed(fv(rec), wanted)
        if diff:
            diff[stamp_field] = ts
            if app == cfg.app_project_master:
                check_system_fields(diff, lib.settings)  # never anything people typed
            try:
                client.edit_submission(app, sid, diff)
            except ClappiaError as ex:
                errors.append(f"{label} {sid}: {ex}")
                return
        edits.append((f"{label} {sid}", diff))

    if len(pms) == 1:
        write(cfg.app_project_master, pms[0], pm_fields(light, ev), "last_engine_run", "Project Master")
    else:
        errors.append(f"{len(pms)} Project Master records for {pc}; expected 1 (not written)")
    if len(decisions) == 1:
        write(cfg.app_gate_decision, decisions[0], gd_fields(ev, blockers), "readiness_checked_at",
              f"Gate Decision {GATE}")

    _report(out, pc, light, ev, blockers, edits, errors)
    return EXIT_ERRORS if errors else EXIT_OK
