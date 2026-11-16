"""status tests. Same FakeClappia + network block as test_inject; no real HTTP."""
import io
import json
from datetime import datetime, timezone

import pytest

from stagegate.clappia import ClappiaClient
from stagegate.engine import build_checklist, load_library
from stagegate.inject import EXIT_ERRORS, EXIT_OK, EXIT_REFUSED, gate_decision_record
from stagegate.status import AWAITING, run_status
from test_inject import ENV, FX, FakeClappia, no_network  # noqa: F401  (no_network: autouse fixture)

T1 = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 16, 10, 30, 0, tzinfo=timezone.utc)
CLOSED = {"Standard": "Done", "Critical": "Approve", "Note": "Taken into account"}


def seed_injected(fake, name, close=lambda it: False, decision=None):
    """Seed PM, Gate Items and the G1 decision as inject leaves them; item_status stands in for
    the Clappia formula (closed items get their class's closing status, open ones stay blank)."""
    d = json.load(open(FX / f"{name}.json", encoding="utf-8"))
    items, _ = build_checklist(d["project"], d["sidecar"], load_library())
    ids = {"PM": fake.seed("PM", d["project"])}
    for it in items:
        rec = it.to_clappia()
        if close(it):
            rec["item_status"] = CLOSED[it.item_class]
        fake.seed("GI", rec)
    ids["GD"] = fake.seed("GD", {**gate_decision_record(d["project"]), **(decision or {})})
    return items, ids


def run(fake, name="FX-1", now=T1, **kw):
    out = io.StringIO()
    kw.setdefault("fixture", str(FX / f"{name}.json"))
    code = run_status(env=dict(kw.pop("env", ENV)), out=out, now=lambda: now,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake), **kw)
    return code, out.getvalue()


def edit_for(fake, app):
    es = [e for e in fake.edits() if e["appId"] == app]
    assert len(es) <= 1
    return es[0]["data"] if es else None


# ---------------------------------------------------------------- lights
def test_fx1_as_created_is_amber():
    fake = FakeClappia()
    items, ids = seed_injected(fake, "FX-1")
    code, out = run(fake)
    assert code == EXIT_OK and "status FX-1 G1: Amber" in out
    assert edit_for(fake, "PM") == {"traffic_light": ["Amber"], "open_critical": "0", "open_standard": "13",
                                    "unacked_notes": "3", "last_engine_run": "2026-11-16T09:00:00Z"}
    gd = edit_for(fake, "GD")
    assert gd["gate_ready"] == ["No"] and gd["readiness_checked_at"] == "2026-11-16T09:00:00Z"
    assert gd["blockers"].startswith("Standard: G1-01") and "Notes: DF-L5, DF-R3, DF-S5" in gd["blockers"]
    assert fake.creates() == []


def test_fx2_is_red_on_g1_criticals():
    fake = FakeClappia()
    seed_injected(fake, "FX-2")
    code, out = run(fake, "FX-2")
    assert code == EXIT_OK and "status FX-2 G1: Red" in out
    blockers = edit_for(fake, "GD")["blockers"]
    assert "Critical: DF-G1, DF-L2, DF-R2 |" in blockers and "DF-R6" not in blockers  # G2 Critical not at G1
    assert edit_for(fake, "PM")["open_critical"] == "3"


def test_fx3_is_red_on_hard_stops():
    fake = FakeClappia()
    items, _ = seed_injected(fake, "FX-3")
    ko = next(i.item_id for i in items if i.item_id.startswith("KO-"))
    code, out = run(fake, "FX-3")
    blockers = edit_for(fake, "GD")["blockers"]
    assert code == EXIT_OK and "status FX-3 G1: Red" in out
    assert blockers.startswith(f"HARD STOP: DF-R5, DF-S2, {ko} | Standard: G1-01") and ko.startswith("KO-")
    assert "Critical:" not in blockers  # hard stops are listed once
    assert blockers.endswith("| Notes: DF-R11")
    assert edit_for(fake, "PM")["traffic_light"] == ["Red"] and edit_for(fake, "PM")["open_critical"] == "3"


def test_all_closed_pass_and_accepted_is_green():
    fake = FakeClappia()
    seed_injected(fake, "FX-1", close=lambda it: True,
                  decision={"gate_decision": "Pass", "ownership_accepted": "Accepted"})
    code, out = run(fake)
    assert code == EXIT_OK and "status FX-1 G1: Green" in out
    assert edit_for(fake, "PM")["traffic_light"] == ["Green"]
    gd = edit_for(fake, "GD")
    assert gd["gate_ready"] == ["Yes"] and gd["blockers"] == "None"


@pytest.mark.parametrize("decision", [None, {"gate_decision": "Pass"}, {"ownership_accepted": "Accepted"},
                                      {"gate_decision": "Hold", "ownership_accepted": "Accepted"}])
def test_ready_without_pass_and_ownership_is_amber(decision):
    fake = FakeClappia()
    seed_injected(fake, "FX-1", close=lambda it: True, decision=decision)
    code, out = run(fake)
    gd = edit_for(fake, "GD")
    assert code == EXIT_OK and "status FX-1 G1: Amber" in out
    assert gd["gate_ready"] == ["Yes"] and gd["blockers"] == AWAITING
    assert edit_for(fake, "PM")["traffic_light"] == ["Amber"]


def test_g2_items_do_not_affect_g1():
    fake = FakeClappia()
    items, _ = seed_injected(fake, "FX-2", close=lambda it: it.gate == "G1",
                             decision={"gate_decision": "Pass", "ownership_accepted": "Accepted"})
    g2 = [i for i in items if i.gate == "G2"]
    assert g2 and all(i.item_class == "Critical" and not i.hard_stop for i in g2)  # DF-R6 left open
    code, out = run(fake, "FX-2")
    assert code == EXIT_OK and "status FX-2 G1: Green" in out and "DF-R6" not in out


def test_item_status_used_as_is_not_rederived():
    fake = FakeClappia()
    # Formula says Critical "Reject" -> still open, even though "ticked"/"decision" fields say otherwise.
    seed_injected(fake, "FX-2", close=lambda it: it.item_id != "DF-G1")
    rec = next(r for r in fake.apps["GI"] if r["submissionFieldValues"]["item_id"] == "DF-G1")
    rec["submissionFieldValues"].update({"item_status": "Reject", "decision": ["Approve"]})
    code, out = run(fake, "FX-2")
    assert "status FX-2 G1: Red" in out and edit_for(fake, "GD")["blockers"] == "Critical: DF-G1"


# ---------------------------------------------------------------- write-back behaviour
def test_second_run_makes_no_edits_even_with_new_timestamp():
    fake = FakeClappia()
    seed_injected(fake, "FX-2")
    run(fake, "FX-2", now=T1)
    n = len(fake.edits())
    assert n == 2
    code, out = run(fake, "FX-2", now=T2)
    assert code == EXIT_OK and len(fake.edits()) == n
    assert out.count(": no change") == 2
    pm = fake.apps["PM"][0]["submissionFieldValues"]
    assert pm["last_engine_run"] == "2026-11-16T09:00:00Z"  # not bumped by the no-op run


def test_only_changed_fields_written_with_stamp():
    fake = FakeClappia()
    items, _ = seed_injected(fake, "FX-1")
    run(fake, now=T1)
    # close one Standard item: counts + blockers change, light stays Amber
    rec = next(r for r in fake.apps["GI"] if r["submissionFieldValues"]["item_id"] == "G1-01")
    rec["submissionFieldValues"]["item_status"] = "Done"
    run(fake, now=T2)
    pm_edits = [e["data"] for e in fake.edits() if e["appId"] == "PM"]
    assert pm_edits[-1] == {"open_standard": "12", "last_engine_run": "2026-11-16T10:30:00Z"}
    gd_edits = [e["data"] for e in fake.edits() if e["appId"] == "GD"]
    assert set(gd_edits[-1]) == {"blockers", "readiness_checked_at"} and "G1-01" not in gd_edits[-1]["blockers"]


def test_project_flag_reads_by_code():
    fake = FakeClappia()
    seed_injected(fake, "FX-1")
    seed_injected(fake, "FX-3")
    code, out = run(fake, fixture=None, project="FX-1")
    assert code == EXIT_OK and "status FX-1 G1: Amber" in out
    assert len([e for e in fake.edits() if e["appId"] == "PM"]) == 1


# ---------------------------------------------------------------- guards + failures
def test_guards():
    fake = FakeClappia()
    code, out = run(fake, env={**ENV, "SG_ENABLED": "false"})
    assert code == EXIT_REFUSED and "status disabled" in out and fake.calls == []
    code, out = run(fake, fixture=None, project="CV-101")
    assert code == EXIT_REFUSED and "Refusing" in out and fake.calls == []
    code, out = run(fake, fixture=None, project="CV-101", allow_live=True)
    assert code == EXIT_ERRORS and "no Gate Items" in out and fake.edits() == []


def test_dry_run_makes_no_calls():
    def factory(cfg):
        raise AssertionError("client built in dry run")
    out = io.StringIO()
    code = run_status(str(FX / "FX-3.json"), dry_run=True, env={"SG_ENABLED": "true"}, out=out,
                      client_factory=factory, now=lambda: T1)
    assert code == EXIT_OK and "status FX-3 G1: Red" in out.getvalue() and "DRY RUN" in out.getvalue()
    out = io.StringIO()
    assert run_status(project="FX-1", dry_run=True, env={"SG_ENABLED": "true"}, out=out,
                      client_factory=factory) == EXIT_REFUSED


def test_missing_decision_reports_error_but_updates_project_master():
    fake = FakeClappia()
    seed_injected(fake, "FX-1")
    fake.apps["GD"].clear()
    code, out = run(fake)
    assert code == EXIT_ERRORS and "no G1 Gate Decision" in out
    assert edit_for(fake, "PM")["traffic_light"] == ["Amber"] and edit_for(fake, "GD") is None


def test_read_failure_writes_nothing():
    fake = FakeClappia()
    seed_injected(fake, "FX-1")
    fake.fail[("/submissions/getSubmissions", "GI")] = "boom"
    code, out = run(fake)
    assert code == EXIT_ERRORS and "nothing written" in out and fake.edits() == []
