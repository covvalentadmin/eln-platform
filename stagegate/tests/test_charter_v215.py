"""V2-15: charter fields + rd_chemists sendable on create, "Must close before" (checkpoint) on Gate Items,
"Not applicable" closes Standard/Critical items, checkpoint_status is a system field, clean CLI errors.
Offline: FakeClappia + the conftest network block."""
import contextlib
import dataclasses
import io
import json
from pathlib import Path

import pytest

from stagegate import cli as cli_mod
from stagegate import inject as inject_mod
from stagegate.cli import main as cli_main
from stagegate.clappia import ClappiaClient, same_value
from stagegate.engine import CHECKPOINT_LABELS, build_checklist, load_library
from stagegate.inject import EXIT_OK, EXIT_REFUSED, run_inject
from stagegate.readiness import evaluate
from test_inject import ENV, FakeClappia

ROOT = Path(__file__).resolve().parent.parent
LIB = load_library()
FX1 = json.loads((ROOT / "fixtures" / "FX-1.json").read_text(encoding="utf-8"))
A, S, D = "aqeedat.kaur.sandhu@covvalent.com", "sales.crams@covvalent.com", "devendar.vanga@covvalent.com"
CHARTER = {
    "customer": "Acme Pharma GmbH",
    "formula_mw": "C8H7FO2, 154.1",
    "stages_in_scope": ["Stage 1 – Lab and sample", "Stage 2 – Pilot"],
    "baseline_route": "Balz-Schiemann from 4-aminoacetophenone",
    "sponsor_email": A,
    "project_lead_email": S,
    "objectives": "Qualified 50 g sample by Q2",
    "out_of_scope": "Stage 3 commercial supply",
    "gmp_status": "Non-GMP",
    "regulatory_note": "EU precursor Cat 3 reagent",
    "spec_document_link": "https://example.com/spec.pdf",
    "method_status": "To be agreed",
    "assumptions": "Yield 62%; RMC basis lab estimate",
    "target_rmc_usd_kg": 42.5,
    "deliverables": "50 g sample, CoA, SDS, technical note",
    "stage_timeline": "Stage 1: 12 weeks",
    "analytical_lead_email": D,
    "process_lead_email": D,
    "procurement_email": S,
    "pilot_lead_email": A,
}
TEAM = {"rd_chemists": f"{D}, {S}"}


def fixture_file(tmp_path, **changes):
    d = json.loads(json.dumps(FX1))
    d["project"].update(changes)
    p = tmp_path / "FX-1-charter.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def inject(fake, path, **kw):
    out = io.StringIO()
    code = run_inject(str(path), env=dict(ENV), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake), **kw)
    return code, out.getvalue()


def kept_lines(out):
    return [line for line in out.splitlines() if line.startswith("  kept Clappia value: ")]


# ---------------------------------------------------------------- 1. charter fields on create
def test_charter_fields_sent_on_create_in_clappia_format(tmp_path):
    assert len(CHARTER) == 20
    fake = FakeClappia()  # rejects any non-list Select value and any non-str/non-list value
    code, out = inject(fake, fixture_file(tmp_path, **CHARTER, **TEAM))
    assert code == EXIT_OK
    (pm,) = fake.creates("PM")
    data = pm["data"]
    assert data["stages_in_scope"] == ["Stage 1 – Lab and sample", "Stage 2 – Pilot"]  # multi-select: the list
    assert data["gmp_status"] == ["Non-GMP"] and data["method_status"] == ["To be agreed"]  # dropdowns
    assert data["target_rmc_usd_kg"] == "42.5"  # number as string
    assert data["rd_chemists"] == f"{D}, {S}"
    for k, v in CHARTER.items():
        if k not in ("stages_in_scope", "gmp_status", "method_status", "target_rmc_usd_kg"):
            assert data[k] == v, k
    assert set(data) == set(FX1["project"]) | set(CHARTER) | set(TEAM)
    assert "would upsert" not in out


def test_dry_run_counts_charter_fields(tmp_path):
    out = io.StringIO()
    assert run_inject(str(fixture_file(tmp_path, **CHARTER, **TEAM)), dry_run=True,
                      env={"SG_ENABLED": "true"}, out=out) == EXIT_OK
    assert "would upsert Project Master FX-1  -- 37 fields" in out.getvalue()


def test_existing_record_charter_changes_kept_not_edited(tmp_path):
    fake = FakeClappia()
    fake.seed("PM", {**FX1["project"], **CHARTER, **TEAM,
                     "objectives": "Changed in Clappia", "gmp_status": "GMP",
                     "stages_in_scope": ["Stage 1 – Lab and sample"]})
    code, out = inject(fake, fixture_file(tmp_path, **CHARTER, **TEAM))
    assert code == EXIT_OK and [e for e in fake.edits() if e["appId"] == "PM"] == []
    assert kept_lines(out) == ["  kept Clappia value: stages_in_scope", "  kept Clappia value: objectives",
                               "  kept Clappia value: gmp_status"]
    assert "kept=3" in out


def test_multi_select_reordered_is_not_a_difference(tmp_path):
    fake = FakeClappia()
    fake.seed("PM", {**FX1["project"], **CHARTER, **TEAM,
                     "stages_in_scope": ["Stage 2 – Pilot", "Stage 1 – Lab and sample"]})
    code, out = inject(fake, fixture_file(tmp_path, **CHARTER, **TEAM))
    assert code == EXIT_OK and kept_lines(out) == [] and "kept=0" in out and fake.edits() == []


@pytest.mark.parametrize("stored,wanted,equal", [
    (["b", "a"], ["a", "b"], True),
    (["a"], ["a", "b"], False),
    (["CIF"], ["CIF"], True),
    ("CIF", ["CIF"], True),
    (None, ["CIF"], False),
    (85, "85", True),
    ("1 MT/yr", "2 MT/yr", False),
    (None, "x", False),
])
def test_same_value(stored, wanted, equal):
    assert same_value(stored, wanted) is equal


@pytest.mark.parametrize("field", ["sponsor_email", "project_lead_email", "analytical_lead_email",
                                   "process_lead_email", "procurement_email", "pilot_lead_email"])
def test_non_pilot_charter_email_refused_before_any_call(tmp_path, field):
    fake = FakeClappia()
    code, out = inject(fake, fixture_file(tmp_path, **{**CHARTER, field: "outsider@gmail.com"}))
    assert code == EXIT_REFUSED and fake.calls == []
    assert f"Projects record FX-1: field '{field}': outsider@gmail.com" in out


def test_non_pilot_second_chemist_refused(tmp_path):
    fake = FakeClappia()
    code, out = inject(fake, fixture_file(tmp_path, rd_chemists=f"{D}, outsider@gmail.com"))
    assert code == EXIT_REFUSED and fake.calls == []
    assert "Projects record FX-1: field 'rd_chemists': outsider@gmail.com" in out


# ---------------------------------------------------------------- 2. checkpoint ("Must close before")
def test_checkpoint_labels():
    assert CHECKPOINT_LABELS == {"pre_experiment": "Before first experiment", "pre_coa": "Before sample CoA",
                                 "gate": "Before gate decision"}
    assert "checkpoint" in LIB.settings["select_fields"]["gate_items"]


def test_g2_core_items_via_preview_path_carry_mapped_labels():
    """Same build path as `preview --core-gate G2` (cli.preview_core_gate)."""
    items, _ = build_checklist(FX1["project"], FX1["sidecar"], dataclasses.replace(LIB, core=LIB.cores["G2"]))
    got = {i.item_id: i.to_clappia()["checkpoint"] for i in items if i.source == "Core template"}
    want = {c["id"]: CHECKPOINT_LABELS[c["checkpoint"]] for c in LIB.cores["G2"]}
    assert got == want and len(got) == 17
    assert got["L-1"] == "Before first experiment" and got["L-8"] == "Before sample CoA"
    assert got["GATE-1"] == "Before gate decision"


def test_every_new_gate_item_sends_checkpoint_as_select_list():
    fake = FakeClappia()
    code, _ = inject(fake, ROOT / "fixtures" / "FX-2.json")
    assert code == EXIT_OK
    gi = fake.creates("GI")
    assert len(gi) == 19 and all(c["data"]["checkpoint"] == ["Before gate decision"] for c in gi)


# ---------------------------------------------------------------- 3. Not applicable closes Standard / Critical
def rec(item_id, cls, status="", gate="G1", hard="No"):
    return {"item_id": item_id, "item_class": cls, "item_status": status, "gate": gate, "hard_stop": hard,
            "superseded": "No"}


def test_standard_not_applicable_is_closed():
    r = evaluate([rec("G1-01", "Standard", "Not applicable"), rec("G1-02", "Standard", "Done")], "G1")
    assert (r["traffic_light"], r["open_standard"], r["blockers"]) == ("Ready", 0, "None")


def test_critical_not_applicable_is_closed():
    r = evaluate([rec("DF-G1", "Critical", "Not applicable"), rec("G1-01", "Standard")], "G1")
    assert r["traffic_light"] == "Amber" and r["open_critical"] == 0
    assert r["blockers"] == "Standard: G1-01"


def test_hard_stop_critical_not_applicable_is_closed():
    open_ = evaluate([rec("DF-R5", "Critical", "Awaiting decision", hard="Yes")], "G1")
    assert open_["traffic_light"] == "Red" and open_["blockers"] == "HARD STOP: DF-R5"
    na = evaluate([rec("DF-R5", "Critical", "Not applicable", hard="Yes")], "G1")
    assert (na["traffic_light"], na["open_critical"], na["blockers"]) == ("Ready", 0, "None")


def test_note_not_applicable_is_not_a_closing_status():
    r = evaluate([rec("DF-S5", "Note", "Not applicable")], "G1")
    assert (r["traffic_light"], r["unacked_notes"], r["blockers"]) == ("Amber", 1, "Notes: DF-S5")


def test_blockers_exclude_not_applicable_items():
    r = evaluate([rec("DF-G1", "Critical", "Not applicable"), rec("DF-L2", "Critical"),
                  rec("G1-01", "Standard", "Not applicable"), rec("G1-02", "Standard"),
                  rec("DF-R6", "Critical", "Not applicable", gate="G2", hard="Yes")], "G1")
    assert r["blockers"] == "Critical: DF-L2 | Standard: G1-02"
    assert "DF-G1" not in r["blockers"] and "G1-01" not in r["blockers"] and "DF-R6" not in r["blockers"]


# ---------------------------------------------------------------- 4. checkpoint_status is a system field
def test_checkpoint_status_is_system_not_written_by_status_yet():
    from stagegate.status import PROJECT_FIELDS_WRITTEN
    assert "checkpoint_status" in LIB.settings["system_fields"]
    assert "checkpoint_status" not in PROJECT_FIELDS_WRITTEN  # V2-12


# ---------------------------------------------------------------- 5. clean CLI errors
def broken_data(tmp_path, file, old, new):
    for f in (ROOT / "data").iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    text = (tmp_path / file).read_text(encoding="utf-8")
    assert old in text
    (tmp_path / file).write_text(text.replace(old, new, 1), encoding="utf-8")
    return tmp_path


def run_cli(argv, capsys):
    code = cli_main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


@pytest.mark.parametrize("argv", [["preview", "FX"], ["inject", "FX", "--dry-run"]])
def test_cli_settings_error_one_line_exit_2(tmp_path, monkeypatch, capsys, argv):
    d = broken_data(tmp_path, "settings.yaml", "checkpoint_status]", "checkpoint_status, volume]")
    monkeypatch.setattr(cli_mod, "load_library", lambda: load_library(d))
    monkeypatch.setattr(inject_mod, "load_library", lambda: load_library(d))
    monkeypatch.setenv("SG_ENABLED", "true")
    argv = [str(ROOT / "fixtures" / "FX-1.json") if a == "FX" else a for a in argv]
    code, out, err = run_cli(argv, capsys)
    assert code == 2 and out == ""
    assert err.splitlines() == ["settings error: settings.yaml: fields in both people_fields and system_fields: ['volume']"]
    assert "Traceback" not in err


def test_cli_template_error_one_line_exit_2(tmp_path, monkeypatch, capsys):
    d = broken_data(tmp_path, "g2_core.yaml", "    checkpoint: pre_coa\n", "    checkpoint: pre_launch\n    colour: red\n")
    monkeypatch.setattr(cli_mod, "load_library", lambda: load_library(d))
    code, out, err = run_cli(["preview", str(ROOT / "fixtures" / "FX-1.json")], capsys)
    assert code == 2 and out == "" and "Traceback" not in err
    (line,) = err.splitlines()
    assert line.startswith("template error: invalid core template: g2_core.yaml: item L-8: key 'colour': unknown key; ")
    assert "key 'checkpoint': unknown value 'pre_launch'" in line
