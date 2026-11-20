"""V2-02: G2 core template (Stage 0 charter + Stage 1 lab/sample). Loaded and validated, not injected
(active_core_gates: [G1]). Offline only: no Clappia client is ever built here."""
import contextlib
import dataclasses
import io
import json
from pathlib import Path

import pytest

from stagegate.cli import main as cli_main
from stagegate.engine import TemplateError, build_checklist, load_library
from stagegate.inject import run_inject

ROOT = Path(__file__).resolve().parent.parent
LIB = load_library()
G2 = LIB.cores["G2"]

ORDER = ["C0-1", "C0-2", "C0-3", "C0-4", "C0-5", "C0-6", "C0-7",
         "L-1", "L-2", "L-3", "L-4", "L-5", "L-6", "L-7", "L-8", "L-9", "GATE-1"]
TABLE = {  # id: (class, hard_stop, owner_role, approver_role, checkpoint)
    "C0-1": ("Critical", False, "Project Lead", "Sponsor", "pre_experiment"),
    "C0-2": ("Note", False, "Analytical lead", "Chemist", "pre_experiment"),
    "C0-3": ("Standard", False, "Project Lead", None, "pre_experiment"),
    "C0-4": ("Standard", False, "Procurement", None, "pre_experiment"),
    "C0-5": ("Standard", False, "Project Lead", None, "pre_experiment"),
    "C0-6": ("Standard", False, "Project Lead", None, "pre_experiment"),
    "C0-7": ("Standard", False, "R&D lead", None, "pre_experiment"),
    "L-1": ("Critical", False, "Chemist", "R&D lead", "pre_experiment"),
    "L-2": ("Standard", False, "Chemist", None, "gate"),
    "L-3": ("Critical", False, "Chemist", "Project Lead", "gate"),
    "L-4": ("Standard", False, "R&D lead", None, "gate"),
    "L-5": ("Standard", False, "R&D lead", None, "gate"),
    "L-6": ("Standard", False, "Analytical lead", None, "gate"),
    "L-7": ("Standard", False, "Costing", None, "gate"),
    "L-8": ("Critical", True, "Analytical lead", "R&D lead", "pre_coa"),
    "L-9": ("Standard", False, "Project Lead", None, "gate"),
    "GATE-1": ("Critical", False, "Project Lead", "Sponsor", "gate"),
}


def fixture(name):
    return json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))


def g2_items(name="FX-1"):
    d = fixture(name)
    items, _ = build_checklist(d["project"], d["sidecar"], dataclasses.replace(LIB, core=G2))
    return {i.item_id: i for i in items if i.source == "Core template"}


# ---------------------------------------------------------------- template content
def test_seventeen_items_in_table_order_at_g2():
    assert [c["id"] for c in G2] == ORDER
    assert {c["gate"] for c in G2} == {"G2"}


def test_class_counts_and_single_hard_stop():
    classes = [c["class"] for c in G2]
    assert (classes.count("Critical"), classes.count("Standard"), classes.count("Note")) == (5, 11, 1)
    assert [c["id"] for c in G2 if c["hard_stop"]] == ["L-8"]


def test_every_row_matches_the_approved_table():
    for c in G2:
        assert (c["class"], c["hard_stop"], c["owner_role"], c["approver_role"], c["checkpoint"]) == TABLE[c["id"]], c["id"]


def test_check_and_evidence_text():
    by = {c["id"]: c for c in G2}
    assert by["C0-1"]["item"] == "Charter approved: scope, stages, out-of-scope, success criteria"
    assert by["C0-1"]["criterion"] == "Signed charter"
    assert by["L-2"]["item"] == "Feasibility runs kept within PHA limits (≤ 100 mL RBF, ≤ 400 mL pressure reactor)"
    assert by["L-8"]["item"].startswith("Methods received or equivalent agreed (hard stop)")
    assert by["GATE-1"]["criterion"] == "Customer approval on record"


# ---------------------------------------------------------------- roles
def test_placeholder_roles_are_fallbacks_and_rd_lead_is_real():
    s = LIB.settings
    assert s["role_fallbacks"]["Sponsor"] == "founder_approver_email"
    assert s["role_fallbacks"]["Project Lead"] == "bd_poc_email"
    assert s["role_fallbacks"]["Procurement"] == "bd_poc_email"
    assert s["role_fallbacks"]["Chemist"] == "rd_lead_email"
    assert s["role_fallbacks"]["Costing"] == "bd_poc_email"
    assert s["role_fields"]["R&D lead"] == "rd_lead_email"


@pytest.mark.parametrize("name", ["FX-1", "FX-2", "FX-3", "FX-4"])
def test_every_role_resolves(name):
    p = fixture(name)["project"]
    items = g2_items(name)
    assert list(items) == ORDER or sorted(items) == sorted(ORDER)
    for iid, i in items.items():
        assert i.owner_email, iid
        if i.item_class != "Standard":
            assert i.approver_email, iid
    # spot checks against the resolution rules
    assert (items["C0-1"].approver_email, items["C0-1"].role_fallback) == (p["founder_approver_email"], True)
    assert (items["C0-2"].approver_email, items["C0-2"].role_fallback) == (p["rd_lead_email"], True)   # Chemist
    assert (items["L-1"].approver_email, items["L-1"].role_fallback) == (p["rd_lead_email"], False)    # R&D lead
    assert (items["L-3"].approver_email, items["L-3"].role_fallback) == (p["bd_poc_email"], True)      # Project Lead
    assert (items["L-7"].owner_email, items["L-7"].role_fallback) == (p["bd_poc_email"], True)         # Costing
    assert (items["C0-4"].owner_email, items["C0-4"].role_fallback) == (p["bd_poc_email"], True)       # Procurement
    assert (items["L-4"].owner_email, items["L-4"].role_fallback) == (p["rd_lead_email"], False)       # R&D lead


def test_routing_labels_and_hard_stop():
    items = g2_items()
    assert items["C0-1"].approver_role == "Sponsor"
    assert items["C0-1"].to_clappia()["approver_role"] == "Sponsor (fallback: role holder not set)"
    assert items["C0-2"].approver_role == "Chemist"  # named-role Note, not Receiving POC
    assert items["L-8"].hard_stop and items["L-8"].to_clappia()["hard_stop"] == "Yes"
    assert [i for i, it in items.items() if it.hard_stop] == ["L-8"]
    assert {i.checkpoint for i in items.values()} == {"pre_experiment", "gate", "pre_coa"}


def test_checkpoint_not_sent_and_no_new_payload_keys():
    g1 = build_checklist(fixture("FX-2")["project"], fixture("FX-2")["sidecar"], LIB)[0]
    known = set().union(*(set(i.to_clappia()) for i in g1))
    for iid, i in g2_items().items():
        payload = i.to_clappia()
        assert "checkpoint" not in payload and set(payload) <= known, iid


# ---------------------------------------------------------------- not injected (active_core_gates)
def test_only_g1_core_is_active():
    assert LIB.settings["active_core_gates"] == ["G1"]
    assert sorted(LIB.cores) == ["G1", "G2"]
    assert len(LIB.core) == 13 and {c["gate"] for c in LIB.core} == {"G1"}


@pytest.mark.parametrize("name", ["FX-1", "FX-2", "FX-3", "FX-4"])
def test_build_and_inject_dry_run_have_no_g2_core_items(name):
    d = fixture(name)
    items, _ = build_checklist(d["project"], d["sidecar"], LIB)
    assert not [i for i in items if i.source == "Core template" and i.gate == "G2"]
    out = io.StringIO()
    run_inject(str(ROOT / "fixtures" / f"{name}.json"), dry_run=True, env={"SG_ENABLED": "true"}, out=out,
               client_factory=lambda cfg: pytest.fail("dry run built a Clappia client"))
    assert not any(f"|G2|{iid}" in out.getvalue() for iid in ORDER)


def test_unknown_active_gate_is_an_error(tmp_path):
    for f in (ROOT / "data").iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    s = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(s.replace("active_core_gates: [G1]", "active_core_gates: [G1, G9]"),
                                            encoding="utf-8")
    with pytest.raises(TemplateError, match=r"active_core_gates.*G9"):
        load_library(tmp_path)


def test_activating_g2_would_add_its_items(tmp_path):
    """Sanity check for V2-11: the switch is the setting alone."""
    for f in (ROOT / "data").iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    s = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(s.replace("active_core_gates: [G1]", "active_core_gates: [G1, G2]"),
                                            encoding="utf-8")
    lib = load_library(tmp_path)
    assert len(lib.core) == 30


# ---------------------------------------------------------------- preview --core-gate
def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(list(argv))
    return code, buf.getvalue()


def test_preview_core_gate_g2_shows_17_rows():
    code, out = run_cli("preview", str(ROOT / "fixtures" / "FX-1.json"), "--core-gate", "G2")
    rows = [line for line in out.splitlines() if line.startswith("G2   ")]  # table rows (padded gate column)
    assert code == 0 and len(rows) == 17
    assert [r.split()[1] for r in rows] == ORDER
    assert "G2 core template: 17 items; not active (active_core_gates: G1)" in out
    l8 = next(r for r in rows if r.split()[1] == "L-8")
    assert l8.split()[2:5] == ["Critical", "Y", "pre_coa"]


def test_preview_unknown_core_gate():
    code, out = run_cli("preview", str(ROOT / "fixtures" / "FX-1.json"), "--core-gate", "G9")
    assert code == 2 and out == ""
