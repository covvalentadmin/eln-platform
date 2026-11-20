"""V2-03: named charter roles (field -> fallback), owner_fallback vs role_fallback, routing-only fields
never sent, and the pilot-users-only guard. Offline: FakeClappia + the conftest network block."""
import contextlib
import dataclasses
import io
import json
import textwrap
from pathlib import Path

import pytest

from stagegate import inject as inject_mod
from stagegate import status as status_mod
from stagegate.cli import main as cli_main
from stagegate.clappia import ClappiaClient
from stagegate.engine import build_checklist, load_core_template, load_library
from stagegate.inject import EXIT_OK, EXIT_REFUSED, run_inject
from stagegate.status import run_status
from test_inject import ENV, FakeClappia

ROOT = Path(__file__).resolve().parent.parent
LIB = load_library()
BASE = {"project_code": "FX-T", "bd_poc_email": "bd@x.com", "rd_lead_email": "rd@x.com",
        "founder_approver_email": "founder@x.com", "csio_approver_email": "csio@x.com"}
SIDECAR = {"project_code": "FX-T", "run_id": "r1", "run_date": "2026-11-20", "rows": []}

ROUTED = [  # role, own field, fallback field
    ("Sponsor", "sponsor_email", "founder_approver_email"),
    ("Project Lead", "project_lead_email", "bd_poc_email"),
    ("Chemist", "rd_chemists", "rd_lead_email"),
    ("Analytical lead", "analytical_lead_email", "rd_lead_email"),
    ("Procurement", "procurement_email", "bd_poc_email"),
    ("Process engineer", "process_lead_email", "rd_lead_email"),
    ("Pilot coordination", "pilot_lead_email", "founder_approver_email"),
]


def one_item(tmp_path, project, **item):
    """Build a single core item X-01 from an inline template, for `project`."""
    keys = {"id": "X-01", "item": "Thing", "criterion": "Done", **item}
    body = "\n".join(f"    {k}: {v}" for k, v in keys.items()).replace("    id:", "  - id:", 1)
    p = tmp_path / "t_core.yaml"
    p.write_text(f"version: 1\ngate: G2\nitems:\n{body}\n", encoding="utf-8")
    lib = dataclasses.replace(LIB, core=load_core_template(p, LIB.settings))
    items, _ = build_checklist({**project, "project_code": "FX-T"}, SIDECAR, lib)
    return next(i for i in items if i.item_id == "X-01")


# ---------------------------------------------------------------- routing: field -> fallback
def test_routing_table_in_settings():
    r = LIB.settings["role_routing"]
    assert [(role, r[role]["field"], r[role]["fallback"]) for role, _, _ in ROUTED] == ROUTED
    assert r["Chemist"].get("multi") is True
    assert "Analytical lead" not in LIB.settings["role_fallbacks"]


@pytest.mark.parametrize("role,fld,fb", ROUTED, ids=[r[0] for r in ROUTED])
def test_owner_role_field_set_vs_empty(tmp_path, role, fld, fb):
    i = one_item(tmp_path, {**BASE, fld: "holder@x.com"}, owner_role=role)
    assert (i.owner_email, i.owner_fallback) == ("holder@x.com", False)
    for empty in ({}, {fld: ""}, {fld: "   "}):
        i = one_item(tmp_path, {**BASE, **empty}, owner_role=role)
        assert (i.owner_email, i.owner_fallback) == (BASE[fb], True), empty


@pytest.mark.parametrize("role,fld,fb", ROUTED, ids=[r[0] for r in ROUTED])
def test_approver_role_field_set_vs_empty(tmp_path, role, fld, fb):
    kw = {"owner_role": "BD POC", "class": "Critical", "approver_role": role}
    i = one_item(tmp_path, {**BASE, fld: "holder@x.com"}, **kw)
    assert (i.approver_email, i.role_fallback, i.approver_role) == ("holder@x.com", False, role)
    assert i.to_clappia()["approver_role"] == role
    i = one_item(tmp_path, {**BASE, fld: ""}, **kw)
    assert (i.approver_email, i.role_fallback) == (BASE[fb], True)
    assert i.to_clappia()["approver_role"] == f"{role} (fallback: role holder not set)"


@pytest.mark.parametrize("value,expected,fallback", [
    ("chem1@x.com, chem2@x.com", "chem1@x.com", False),
    ("chem1@x.com,chem2@x.com", "chem1@x.com", False),
    ("  , chem2@x.com", "chem2@x.com", False),
    ("", "rd@x.com", True),
    (" , ", "rd@x.com", True),
])
def test_chemist_uses_first_rd_chemists_address(tmp_path, value, expected, fallback):
    i = one_item(tmp_path, {**BASE, "rd_chemists": value}, owner_role="Chemist")
    assert (i.owner_email, i.owner_fallback) == (expected, fallback)


def test_unchanged_roles():
    s = LIB.settings
    assert s["role_fields"]["R&D lead"] == "rd_lead_email"
    assert s["role_fallbacks"]["Costing"] == "bd_poc_email"


# ---------------------------------------------------------------- owner_fallback vs role_fallback
def g2(project, item_id):
    items, _ = build_checklist(project, SIDECAR, dataclasses.replace(LIB, core=LIB.cores["G2"]))
    return next(i for i in items if i.item_id == item_id)


def test_owner_and_approver_flags_are_independent():
    # C0-1: owner Project Lead, approver Sponsor
    i = g2({**BASE, "project_lead_email": "lead@x.com"}, "C0-1")
    assert (i.owner_email, i.owner_fallback, i.approver_email, i.role_fallback) == \
           ("lead@x.com", False, "founder@x.com", True)
    i = g2({**BASE, "sponsor_email": "sponsor@x.com"}, "C0-1")
    assert (i.owner_email, i.owner_fallback, i.approver_email, i.role_fallback) == \
           ("bd@x.com", True, "sponsor@x.com", False)
    i = g2({**BASE, "project_lead_email": "lead@x.com", "sponsor_email": "sponsor@x.com"}, "C0-1")
    assert (i.owner_fallback, i.role_fallback) == (False, False)


def test_flag_rule_owner_is_bd_poc_not_a_fallback():
    d = json.loads((ROOT / "fixtures" / "FX-2.json").read_text(encoding="utf-8"))
    items, _ = build_checklist(d["project"], d["sidecar"], LIB)
    dfg1 = next(i for i in items if i.item_id == "DF-G1")
    assert (dfg1.owner_email, dfg1.owner_fallback, dfg1.role_fallback) == ("sales.crams@covvalent.com", False, True)


def test_internal_flags_never_sent():
    i = g2({**BASE}, "C0-1")
    payload = i.to_clappia()
    assert "owner_fallback" not in payload and "role_fallback" not in payload


# ---------------------------------------------------------------- routing-only fields never sent
ROUTING_EXTRA = {"sponsor_email": "aqeedat.kaur.sandhu@covvalent.com",
                 "project_lead_email": "sales.crams@covvalent.com",
                 "rd_chemists": "devendar.vanga@covvalent.com, sales.crams@covvalent.com"}


def write_fixture(tmp_path, name="FX-1", **project_changes):
    d = json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    d["project"].update(project_changes)
    p = tmp_path / f"{name}-variant.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_routing_fields_not_sent_to_clappia(tmp_path):
    path = write_fixture(tmp_path, **ROUTING_EXTRA)
    fake = FakeClappia()
    out = io.StringIO()
    code = run_inject(str(path), env=dict(ENV), out=out, client_factory=lambda cfg: ClappiaClient(cfg, transport=fake))
    assert code == EXIT_OK
    (pm,) = fake.creates("PM")
    assert not set(ROUTING_EXTRA) & set(pm["data"]), "routing-only field sent"
    sent_keys = set().union(*(set(c["data"]) for c in fake.creates()))
    assert not set(ROUTING_EXTRA) & sent_keys


def test_dry_run_field_count_excludes_routing_fields(tmp_path):
    out = io.StringIO()
    assert run_inject(str(write_fixture(tmp_path, **ROUTING_EXTRA)), dry_run=True,
                      env={"SG_ENABLED": "true"}, out=out) == EXIT_OK
    assert "would upsert Project Master FX-1  -- 16 fields" in out.getvalue()


# ---------------------------------------------------------------- pilot allowlist
OUTSIDER = "outsider@gmail.com"


def no_client(cfg):
    raise AssertionError("Clappia client built despite allowlist violation")


def test_allowlist_settings():
    s = LIB.settings
    assert s["enforce_pilot_allowlist"] is True
    assert sorted(s["pilot_allowlist"]) == ["aqeedat.kaur.sandhu@covvalent.com", "devendar.vanga@covvalent.com",
                                            "sales.crams@covvalent.com"]


@pytest.mark.parametrize("mode", ["inject", "inject --dry-run", "status", "status --dry-run"])
def test_non_pilot_project_email_refused_before_any_call(tmp_path, mode):
    path = write_fixture(tmp_path, bd_poc_email=OUTSIDER)
    fake = FakeClappia()
    out = io.StringIO()
    factory = lambda cfg: ClappiaClient(cfg, transport=fake)  # noqa: E731
    dry = mode.endswith("--dry-run")
    if mode.startswith("inject"):
        code = run_inject(str(path), dry_run=dry, env=dict(ENV), out=out, client_factory=factory)
    else:
        code = run_status(str(path), dry_run=dry, env=dict(ENV), out=out, client_factory=factory)
    text = out.getvalue()
    assert code == EXIT_REFUSED and code != 0
    assert fake.calls == []  # zero network calls
    assert "refused" in text and "pilot_allowlist" in text
    assert f"Projects record FX-1: field 'bd_poc_email': {OUTSIDER}" in text
    assert f"Gate Item FX-1|G1|G1-01: field 'owner_email': {OUTSIDER}" in text  # BD POC owns G1-01
    assert "would create" not in text and "status FX-1" not in text  # nothing planned or written


def test_non_pilot_receiver_names_decision_field(tmp_path):
    path = write_fixture(tmp_path, rd_lead_email=OUTSIDER)
    out = io.StringIO()
    assert run_inject(str(path), dry_run=True, env=dict(ENV), out=out, client_factory=no_client) == EXIT_REFUSED
    text = out.getvalue()
    assert f"Gate Decision FX-1|G1: field 'receiving_poc_email': {OUTSIDER}" in text
    assert f"Gate Item FX-1|G1|DF-R3: field 'approver_email': {OUTSIDER}" in text  # Note -> Receiving POC


def test_allowlist_is_case_insensitive(tmp_path):
    path = write_fixture(tmp_path, bd_poc_email="Sales.Crams@Covvalent.com")
    out = io.StringIO()
    assert run_inject(str(path), dry_run=True, env=dict(ENV), out=out) == EXIT_OK


def test_unwritten_routing_field_is_not_checked(tmp_path):
    """sponsor_email is never sent, and no active (G1) item routes to Sponsor, so nothing writes it."""
    path = write_fixture(tmp_path, sponsor_email=OUTSIDER)
    out = io.StringIO()
    assert run_inject(str(path), dry_run=True, env=dict(ENV), out=out) == EXIT_OK


def test_status_project_mode_checks_reads_before_any_write():
    fake = FakeClappia()
    d = json.loads((ROOT / "fixtures" / "FX-1.json").read_text(encoding="utf-8"))
    items, _ = build_checklist(d["project"], d["sidecar"], LIB)
    fake.seed("PM", d["project"])
    for it in items:
        rec = it.to_clappia()
        if it.item_id == "DF-S5":
            rec["approver_email"] = OUTSIDER
        fake.seed("GI", rec)
    fake.seed("GD", inject_mod.gate_decision_record(d["project"]))
    out = io.StringIO()
    code = run_status(project="FX-1", env=dict(ENV), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake))
    text = out.getvalue()
    assert code == EXIT_REFUSED
    assert f"Gate Item FX-1|G1|DF-S5: field 'approver_email': {OUTSIDER}" in text and "Nothing written" in text
    assert fake.edits() == [] and fake.creates() == []
    assert {p for p, _ in fake.calls} == {"/submissions/getSubmissions"}  # reads only


def test_guard_off_when_not_enforced(tmp_path, monkeypatch):
    lib = dataclasses.replace(LIB, settings={**LIB.settings, "enforce_pilot_allowlist": False})
    monkeypatch.setattr(inject_mod, "load_library", lambda: lib)
    monkeypatch.setattr(status_mod, "load_library", lambda: lib)
    path = write_fixture(tmp_path, bd_poc_email=OUTSIDER)
    assert run_inject(str(path), dry_run=True, env=dict(ENV), out=io.StringIO()) == EXIT_OK
    assert run_status(str(path), dry_run=True, env=dict(ENV), out=io.StringIO()) == EXIT_OK


@pytest.mark.parametrize("name", ["FX-1", "FX-2", "FX-3", "FX-4"])
def test_pilot_fixtures_pass(name):
    out = io.StringIO()
    assert run_inject(str(ROOT / "fixtures" / f"{name}.json"), dry_run=True, env=dict(ENV), out=out,
                      client_factory=no_client) == EXIT_OK


# ---------------------------------------------------------------- preview --core-gate marking
def test_preview_core_gate_marks_owner_and_approver_separately():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli_main(["preview", str(ROOT / "fixtures" / "FX-1.json"), "--core-gate", "G2"]) == 0
    rows = {line.split()[1]: line for line in buf.getvalue().splitlines() if line.startswith("G2   ")}
    assert len(rows) == 17

    def owner_approver(iid):
        rest = rows[iid].split(None, 5)[5]  # after GATE ITEM CLASS HS CHECKPOINT
        owner, _, approver = rest.partition("  ")
        return owner.strip(), approver.strip()

    # C0-1: owner Project Lead (fallback), approver Sponsor (fallback)
    assert owner_approver("C0-1") == ("sales.crams@covvalent.com [fallback]", "aqeedat.kaur.sandhu@covvalent.com [fallback]")
    # L-1: owner Chemist (fallback, no rd_chemists), approver R&D lead (real field)
    assert owner_approver("L-1") == ("devendar.vanga@covvalent.com [fallback]", "devendar.vanga@covvalent.com")
    # L-8: owner Analytical lead (fallback), approver R&D lead (real)
    assert owner_approver("L-8") == ("devendar.vanga@covvalent.com [fallback]", "devendar.vanga@covvalent.com")
    # C0-7: Standard, owner R&D lead (real) -> no flag, no approver
    assert owner_approver("C0-7") == ("devendar.vanga@covvalent.com", "")
