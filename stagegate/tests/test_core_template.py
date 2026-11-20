"""V2-01: core-template schema (class / hard_stop / owner / approver / checkpoint), validation,
and core Critical/Note items routing and counting exactly like flag-rule items. Offline only."""
import dataclasses
import textwrap

import pytest

from stagegate.clappia import norm_value
from stagegate.engine import (CORE_OPTIONAL, TemplateError, build_checklist, load_core_template,
                              load_library)
from stagegate.readiness import evaluate

LIB = load_library()
PROJECT = {"project_code": "FX-T", "bd_poc_email": "bd@x.com", "rd_lead_email": "rd@x.com",
           "founder_approver_email": "founder@x.com", "csio_approver_email": "csio@x.com"}
SIDECAR = {"project_code": "FX-T", "run_id": "r1", "run_date": "2026-11-20", "rows": []}

INLINE = """
version: 1
gate: G1
items:
  - id: T-01
    item: Hazard review signed
    criterion: Signed hazard review on file
    owner_role: R&D POC
    class: Critical
    hard_stop: true
    approver_role: CSIO
    checkpoint: pre_experiment
  - id: T-02
    item: Supplier lead time noted
    criterion: Lead time recorded
    owner_role: BD POC
    class: Note
    approver_role: Receiving POC
    checkpoint: pre_coa
  - id: T-03
    item: Folder created
    criterion: Project folder exists
    owner_role: PM
"""


def write(tmp_path, text, name="test_core.yaml"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def build(tmp_path, text, rows=(), name="test_core.yaml"):
    core = load_core_template(write(tmp_path, text, name), LIB.settings)
    lib = dataclasses.replace(LIB, core=core)
    items, _ = build_checklist(PROJECT, {**SIDECAR, "rows": list(rows)}, lib)
    return {i.item_id: i for i in items}


def item_yaml(**kw):
    base = {"id": "X-01", "item": "Thing", "criterion": "Done", "owner_role": "BD POC", **kw}
    lines = []
    for k, v in base.items():
        if v is True or v is False:
            v = str(v).lower()
        lines.append(f"    {k}: {v}")
    lines[0] = "  - " + lines[0].lstrip()
    return "version: 1\ngate: G1\nitems:\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- defaults
def test_g1_core_loads_with_todays_defaults():
    assert len(LIB.core) == 13
    for c in LIB.core:
        assert (c["class"], c["hard_stop"], c["approver_role"], c["checkpoint"], c["gate"]) == \
               ("Standard", False, None, "gate", "G1"), c["id"]


def test_minimal_item_gets_every_default(tmp_path):
    (c,) = load_core_template(write(tmp_path, item_yaml()), LIB.settings)
    for k, v in CORE_OPTIONAL.items():
        assert c[k] == v, k


# ---------------------------------------------------------------- validation
BAD = [
    ("unknown key", item_yaml(colour="red"), "X-01", "colour", "unknown key"),
    ("unknown class", item_yaml(**{"class": "Major"}), "X-01", "class", "unknown value 'Major'"),
    ("unknown checkpoint", item_yaml(checkpoint="pre_launch"), "X-01", "checkpoint", "unknown value 'pre_launch'"),
    ("hard_stop not bool", item_yaml(**{"class": "Critical", "approver_role": "CSIO", "hard_stop": "maybe"}),
     "X-01", "hard_stop", "must be true or false"),
    ("hard_stop on Note", item_yaml(**{"class": "Note", "approver_role": "Receiving POC", "hard_stop": True}),
     "X-01", "hard_stop", "true is only allowed on class Critical (class is Note)"),
    ("hard_stop on Standard", item_yaml(hard_stop=True), "X-01", "hard_stop",
     "true is only allowed on class Critical (class is Standard)"),
    ("Critical without approver", item_yaml(**{"class": "Critical"}), "X-01", "approver_role", "required on class Critical"),
    ("Note without approver", item_yaml(**{"class": "Note"}), "X-01", "approver_role", "required on class Note"),
    ("approver on Standard", item_yaml(approver_role="CSIO"), "X-01", "approver_role", "not allowed on class Standard"),
    ("unknown approver role", item_yaml(**{"class": "Critical", "approver_role": "CFO"}),
     "X-01", "approver_role", "unknown role 'CFO'"),
    ("Receiving POC on Critical", item_yaml(**{"class": "Critical", "approver_role": "Receiving POC"}),
     "X-01", "approver_role", "unknown role 'Receiving POC' for class Critical"),
    ("unknown owner role", item_yaml(owner_role="Janitor"), "X-01", "owner_role", "unknown role 'Janitor'"),
    ("missing owner role", item_yaml(owner_role="''"), "X-01", "owner_role", "required non-empty string"),
]


@pytest.mark.parametrize("label,text,item,key,msg", BAD, ids=[b[0] for b in BAD])
def test_validation_error_names_file_item_and_key(tmp_path, label, text, item, key, msg):
    with pytest.raises(TemplateError) as ei:
        load_core_template(write(tmp_path, text, "bad_core.yaml"), LIB.settings)
    assert f"bad_core.yaml: item {item}: key '{key}': {msg}" in str(ei.value)


def test_duplicate_item_ids(tmp_path):
    text = item_yaml() + item_yaml().split("items:\n", 1)[1]
    with pytest.raises(TemplateError, match=r"dup_core.yaml: item X-01: key 'id': duplicate item ID"):
        load_core_template(write(tmp_path, text, "dup_core.yaml"), LIB.settings)


def test_all_errors_reported_together(tmp_path):
    text = item_yaml(**{"class": "Critical", "colour": "red"})  # missing approver + unknown key
    with pytest.raises(TemplateError) as ei:
        load_core_template(write(tmp_path, text, "bad_core.yaml"), LIB.settings)
    assert "key 'colour'" in str(ei.value) and "key 'approver_role'" in str(ei.value)


def test_missing_gate_header(tmp_path):
    with pytest.raises(TemplateError, match=r"nogate.yaml: key 'gate'"):
        load_core_template(write(tmp_path, item_yaml().replace("gate: G1\n", ""), "nogate.yaml"), LIB.settings)


# ---------------------------------------------------------------- inline template: classes and approvers
def test_inline_template_classes_and_approvers(tmp_path):
    items = build(tmp_path, INLINE)
    crit, note, std = items["T-01"], items["T-02"], items["T-03"]
    assert (crit.item_class, crit.hard_stop, crit.approver_role, crit.approver_email, crit.role_fallback) == \
           ("Critical", True, "CSIO", "csio@x.com", False)
    assert crit.owner_email == "rd@x.com" and crit.checkpoint == "pre_experiment"
    assert (note.item_class, note.hard_stop, note.approver_role, note.approver_email, note.role_fallback) == \
           ("Note", False, "Receiving POC", "rd@x.com", False)
    assert note.owner_email == "bd@x.com" and note.checkpoint == "pre_coa"
    # Standard core items are unchanged: owner label, no approver email
    assert (std.item_class, std.hard_stop, std.approver_role, std.approver_email) == \
           ("Standard", False, "Owner: PM", "")
    assert std.owner_email == "bd@x.com" and std.role_fallback  # PM falls back to bd_poc_email


def test_core_note_with_named_role_routes_to_that_role(tmp_path):
    text = item_yaml(**{"class": "Note", "approver_role": "Founders"})
    i = build(tmp_path, text)["X-01"]
    assert (i.approver_role, i.approver_email, i.role_fallback) == ("Founders", "founder@x.com", False)


def test_core_critical_routes_exactly_like_flag_rule_critical(tmp_path):
    # DF-R5: hard_stop rule, approver_roles [CSIO]; score 4 -> Critical, hard stop
    items = build(tmp_path, item_yaml(**{"class": "Critical", "hard_stop": True, "approver_role": "CSIO"}),
                  rows=[{"stage": "R&D", "risk": "x", "score": 4, "confidence": "High", "learning_id": "R-004"}])
    core, flag = items["X-01"], items["DF-R5"]
    fields = ("item_class", "hard_stop", "approver_role", "approver_email", "role_fallback", "owner_email")
    assert [getattr(core, f) for f in fields] == [getattr(flag, f) for f in fields]


def test_core_note_routes_exactly_like_flag_rule_note(tmp_path):
    items = build(tmp_path, item_yaml(**{"class": "Note", "approver_role": "Receiving POC"}),
                  rows=[{"stage": "Sourcing", "risk": "x", "score": 3, "confidence": "High", "learning_id": "S-003"}])
    core, flag = items["X-01"], items["DF-S5"]
    fields = ("item_class", "hard_stop", "approver_role", "approver_email", "role_fallback", "owner_email")
    assert [getattr(core, f) for f in fields] == [getattr(flag, f) for f in fields]


def test_gate_comes_from_template_file(tmp_path):
    text = item_yaml(**{"class": "Note", "approver_role": "Receiving POC"}).replace("gate: G1", "gate: G2")
    i = build(tmp_path, text)["X-01"]
    assert i.gate == "G2" and i.idempotency_key == "FX-T|G2|X-01"
    assert (i.approver_email, i.role_fallback) == ("rd@x.com", True)  # no G2 receiving POC field yet


# ---------------------------------------------------------------- status counts + payload
def test_core_items_count_like_flag_items(tmp_path):
    items = build(tmp_path, INLINE)
    records = [{k: norm_value(v) for k, v in i.to_clappia().items()} for i in items.values()]
    ev = evaluate(records, "G1")
    assert ev["traffic_light"] == "Red"
    assert ev["blockers"].startswith("HARD STOP: T-01 | Standard: T-03 | Notes: T-02")
    assert (ev["open_critical"], ev["open_standard"], ev["unacked_notes"]) == (1, 1, 1)


def test_checkpoint_and_internal_roles_never_sent(tmp_path):
    items = build(tmp_path, INLINE, rows=[{"stage": "R&D", "risk": "x", "score": 4, "confidence": "High",
                                           "learning_id": "R-004"}])
    flag_keys = set(items["DF-R5"].to_clappia())
    for iid in ("T-01", "T-02", "T-03"):
        payload = items[iid].to_clappia()
        assert "checkpoint" not in payload and "approver_roles" not in payload
        assert set(payload) <= flag_keys  # no new Clappia key
