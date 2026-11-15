import copy
import itertools
import json
from pathlib import Path

import pytest

from stagegate.engine import RANK, build_checklist, class_from_score, load_library, validate_sidecar

LIB = load_library()
FX = Path(__file__).resolve().parent.parent / "fixtures"
PROJECT = {
    "project_code": "FX-T",
    "bd_poc_email": "bd@x.com", "rd_lead_email": "rd@x.com",
    "founder_approver_email": "founder@x.com", "csio_approver_email": "csio@x.com",
}


def sc(rows, mandatory=None, code="FX-T"):
    d = {"project_code": code, "run_id": "r1", "run_date": "2026-11-13", "rows": rows}
    if mandatory is not None:
        d["mandatory"] = mandatory
    return d


def row(score, stage="R&D", risk="x", **kw):
    return {"stage": stage, "risk": risk, "score": score, "confidence": "High", **kw}


def run(rows, mandatory=None):
    items, log = build_checklist(PROJECT, sc(rows, mandatory), LIB)
    return {(i.gate, i.item_id): i for i in items if i.source != "Core template"}, log


# ---------------------------------------------------------------- library integrity
def test_library_counts():
    assert len(LIB.core) == 13
    assert len(LIB.rules) == 15
    assert all(r["gates"][0] == "G1" for r in LIB.rules.values())


def test_core_template_always_present_and_standard():
    items, _ = build_checklist(PROJECT, sc([]), LIB)
    core = [i for i in items if i.source == "Core template"]
    assert [i.item_id for i in core] == [f"G1-{n:02d}" for n in range(1, 14)]
    assert {i.item_class for i in core} == {"Standard"}


# ---------------------------------------------------------------- classification matrix
@pytest.mark.parametrize("score,expected", [(5, "Critical"), (4, "Critical"), (3, "Note"), (2, None), (1, None)])
def test_class_from_score(score, expected):
    assert class_from_score(score) == expected


def test_low_scores_never_reach_checklist():
    items, log = run([row(1), row(2, risk="y")])
    assert items == {}
    assert log["rows_skipped_low_score"] == 2 and log["rows_imported"] == 0


def test_score_overrides_rule_default_both_directions():
    # DF-S5 default Note; score 4 -> Critical
    items, _ = run([row(4, stage="Sourcing", learning_id="S-003")])
    assert items[("G1", "DF-S5")].item_class == "Critical"
    # DF-L2 default Critical; score 3 -> Note
    items, _ = run([row(3, stage="Logistics", learning_id="LOG-002")])
    assert items[("G1", "DF-L2")].item_class == "Note"


def test_hard_stop_rule_needs_critical():
    items, _ = run([row(4, learning_id="R-004")])  # DF-R5 hard_stop rule, score 4
    assert items[("G1", "DF-R5")].hard_stop is True
    items, _ = run([row(3, learning_id="R-004")])  # score 3 -> Note, no hard stop
    i = items[("G1", "DF-R5")]
    assert i.item_class == "Note" and i.hard_stop is False


def test_score5_always_hard_stop_at_g1_even_unmapped_or_deferred():
    items, log = run([row(5, risk="unmapped thing"), row(5, learning_id="TT-001", risk="exotherm")])
    assert all(i.gate == "G1" and i.hard_stop and i.item_class == "Critical" for i in items.values())
    assert log["rows_unmapped"] == 1 and log["rows_deferred_rule"] == 1
    assert ("G1", "DF-T1") in items  # deferred G3 rule pulled to G1 by score 5


def test_score4_deferred_rule_lands_at_target_gate():
    items, _ = run([row(4, learning_id="R-003")])
    assert ("G2", "DF-R6") in items and items[("G2", "DF-R6")].item_class == "Critical"


def test_unmapped_rows_never_dropped():
    items, log = run([row(3, risk="a"), row(4, risk="b")])
    assert log["rows_unmapped"] == 2 and len(items) == 2
    assert {i.item_class for i in items.values()} == {"Note", "Critical"}


# ---------------------------------------------------------------- raise-only property
@pytest.mark.parametrize("score,lm,mand", list(itertools.product([3, 4, 5], [False, True], [None, False, True])))
def test_nothing_lowers_class(score, lm, mand):
    """Learning match and mandatory info can only raise, never lower, the score-derived class."""
    mandatory = None if mand is None else [{"rule_id": "DF-S5", "breach": mand}]
    items, _ = run([row(score, stage="Sourcing", learning_id="S-003", learning_match=lm)], mandatory)
    got = items[("G1", "DF-S5")].item_class
    assert RANK[got] >= RANK[class_from_score(score)]
    if lm or mand:
        assert got == "Critical"


# ---------------------------------------------------------------- mandatory items
def test_mandatory_breach_critical_info_note():
    items, _ = run([], [{"rule_id": "DF-L7", "breach": False}, {"rule_id": "DF-G6", "breach": True}])
    assert items[("G1", "DF-L7")].item_class == "Note"
    assert items[("G1", "DF-G6")].item_class == "Critical"


def test_mandatory_unknown_rule_becomes_generic_item():
    items, _ = run([], [{"rule_id": "DF-R4", "breach": True}])
    assert items[("G1", "MI-DF-R4")].item_class == "Critical"


# ---------------------------------------------------------------- merge and idempotency
def test_duplicate_rows_merge_and_raise():
    items, _ = run([row(3, stage="Sourcing", learning_id="S-003", risk="a"),
                    row(4, stage="Sourcing", rule_id="DF-S5", risk="b")])
    i = items[("G1", "DF-S5")]
    assert i.item_class == "Critical" and i.kickoff_score == 4 and len(i.findings) == 2


def test_deterministic_and_unique_keys():
    data = json.loads((FX / "FX-2.json").read_text())
    a, _ = build_checklist(data["project"], data["sidecar"], LIB)
    b, _ = build_checklist(copy.deepcopy(data["project"]), copy.deepcopy(data["sidecar"]), LIB)
    assert [i.to_clappia() for i in a] == [i.to_clappia() for i in b]
    keys = [i.idempotency_key for i in a]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------- approvers
def test_approver_resolution_and_fallback():
    items, _ = run([row(4, stage="Regulatory", rule_id="DF-G1"), row(3, stage="Sourcing", learning_id="S-003")])
    crit = items[("G1", "DF-G1")]
    assert crit.approver_role == "Regulatory head + Founders"
    assert crit.approver_email == "founder@x.com" and crit.role_fallback  # no Regulatory head field yet
    note = items[("G1", "DF-S5")]
    assert note.approver_email == "rd@x.com" and not note.role_fallback  # G1 receiver = R&D lead


def test_g1_11_setting_switches_to_critical():
    lib = load_library()
    lib.settings["g1_11_class"] = "Critical"
    items, _ = build_checklist(PROJECT, sc([]), lib)
    g = next(i for i in items if i.item_id == "G1-11")
    assert g.item_class == "Critical" and g.approver_email == "founder@x.com"


# ---------------------------------------------------------------- validation
def test_validation_field_level_errors():
    bad = {"project_code": "", "run_id": "r", "run_date": "d",
           "rows": [{"stage": "Ops", "risk": "", "score": 7, "confidence": "Sure"}],
           "mandatory": [{"rule_id": "", "breach": "yes"}]}
    errs = validate_sidecar(bad)
    for frag in ["project_code", "rows[0].stage", "rows[0].risk", "rows[0].score",
                 "rows[0].confidence", "mandatory[0].rule_id", "mandatory[0].breach"]:
        assert any(e.startswith(frag) for e in errs), frag
    with pytest.raises(ValueError):
        build_checklist(PROJECT, bad, LIB)


def test_project_code_mismatch_rejected():
    with pytest.raises(ValueError, match="mismatch"):
        build_checklist(PROJECT, sc([], code="FX-OTHER"), LIB)


# ---------------------------------------------------------------- fixtures (expectations written before engine)
EXPECT = {
    "FX-1": {"total": 16, "crit": set(), "notes": {"DF-S5", "DF-R3", "DF-L5"}, "hard": set(), "later": set(), "skipped": 2},
    "FX-2": {"total": 19, "crit": {"DF-R2", "DF-G1", "DF-L2"}, "notes": {"DF-L7", "KO-*"}, "hard": set(),
             "later": {("G2", "DF-R6")}, "skipped": 0},
    "FX-3": {"total": 17, "crit": {"DF-R5", "DF-S2", "KO-*"}, "notes": {"DF-R11"}, "hard": {"DF-R5", "DF-S2", "KO-*"},
             "later": set(), "skipped": 0},
}


def _norm(ids):
    return {("KO-*" if i.startswith("KO-") else i) for i in ids}


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_fixture_expectations(name):
    data = json.loads((FX / f"{name}.json").read_text())
    items, log = build_checklist(data["project"], data["sidecar"], LIB)
    e = EXPECT[name]
    g1 = [i for i in items if i.gate == "G1" and i.source != "Core template"]
    assert len(items) == e["total"]
    assert _norm(i.item_id for i in g1 if i.item_class == "Critical") == e["crit"]
    assert _norm(i.item_id for i in g1 if i.item_class == "Note") == e["notes"]
    assert _norm(i.item_id for i in items if i.hard_stop) == e["hard"]
    assert {(i.gate, i.item_id) for i in items if i.gate != "G1"} == e["later"]
    assert log["rows_skipped_low_score"] == e["skipped"]
    assert all(i.approver_email.endswith("@covvalent.com") for i in items if i.item_class != "Standard")
