"""V2-04: inject never overwrites what people typed in the Projects app.

people_fields are sent only when inject creates the Projects record; an existing record is never
edited (differences are reported as "kept"). system_fields are written only by status. Offline only:
FakeClappia + the conftest network block."""
import dataclasses
import io
import json
from pathlib import Path

import pytest

from stagegate import status as status_mod
from stagegate.clappia import ClappiaClient
from stagegate.engine import SettingsError, build_checklist, load_library
from stagegate.inject import EXIT_OK, EXIT_REFUSED, gate_decision_record, run_inject, to_payload
from stagegate.status import PROJECT_FIELDS_WRITTEN, check_system_fields, run_status
from test_inject import ENV, FakeClappia, wrap

ROOT = Path(__file__).resolve().parent.parent
LIB = load_library()
FX1 = json.loads((ROOT / "fixtures" / "FX-1.json").read_text(encoding="utf-8"))
PEOPLE = ["project_code", "product", "cas_number", "specification", "volume", "timeline", "target_price_usd_kg",
          "end_use", "target_market", "destination", "incoterms", "transit_temperature",
          "bd_poc_email", "rd_lead_email", "founder_approver_email", "csio_approver_email"]
SYSTEM = ["traffic_light", "open_critical", "open_standard", "unacked_notes", "last_engine_run", "current_stage"]


def fixture_file(tmp_path, **changes):
    d = json.loads(json.dumps(FX1))
    d["project"].update(changes)
    p = tmp_path / "FX-1-variant.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def inject(fake, path=None, **kw):
    out = io.StringIO()
    code = run_inject(str(path or ROOT / "fixtures" / "FX-1.json"), env=dict(ENV), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake), **kw)
    return code, out.getvalue()


def pm_edits(fake):
    return [e for e in fake.edits() if e["appId"] == "PM"]


def kept_lines(out):
    return [line for line in out.splitlines() if line.startswith("  kept Clappia value: ")]


# ---------------------------------------------------------------- settings
def test_field_lists_in_settings():
    s = LIB.settings
    assert s["people_fields"] == PEOPLE and s["system_fields"] == SYSTEM
    for name in ("FX-1", "FX-2", "FX-3", "FX-4"):  # people_fields = every field inject sends today
        d = json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
        assert list(d["project"]) == PEOPLE, name


def copy_data(tmp_path, edit):
    for f in (ROOT / "data").iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    s = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    new = edit(s)
    assert new != s
    (tmp_path / "settings.yaml").write_text(new, encoding="utf-8")
    return tmp_path


def test_field_in_both_lists_fails_to_load(tmp_path):
    d = copy_data(tmp_path, lambda s: s.replace("last_engine_run, current_stage]", "last_engine_run, current_stage, volume]"))
    with pytest.raises(SettingsError, match=r"both people_fields and system_fields: \['volume'\]"):
        load_library(d)


def test_routing_field_in_a_list_fails_to_load(tmp_path):
    d = copy_data(tmp_path, lambda s: s.replace("csio_approver_email]", "csio_approver_email, sponsor_email]"))
    with pytest.raises(SettingsError, match=r"role_routing fields must not be in .*sponsor_email"):
        load_library(d)


def test_missing_list_fails_to_load(tmp_path):
    d = copy_data(tmp_path, lambda s: s.replace("system_fields: [", "system_fieldz: ["))
    with pytest.raises(SettingsError, match=r"key 'system_fields': required non-empty list"):
        load_library(d)


# ---------------------------------------------------------------- inject: Projects record
def test_existing_record_two_changed_values_kept_not_edited():
    fake = FakeClappia()
    sid = fake.seed("PM", {**FX1["project"], "volume": "5 MT/yr", "end_use": "Pharma"})
    code, out = inject(fake)
    assert code == EXIT_OK
    assert pm_edits(fake) == [] and fake.creates("PM") == []           # zero Projects writes
    assert kept_lines(out) == ["  kept Clappia value: volume", "  kept Clappia value: end_use"]
    assert "kept=2" in out
    assert fake.apps["PM"][0]["submissionFieldValues"]["volume"] == "5 MT/yr"
    assert fake.apps["PM"][0]["submissionFieldValues"]["end_use"] == ["Pharma"]
    assert f"Project Master FX-1  -- {sid} exists; Clappia values kept, nothing sent" in out
    # Gate Items and the Decision record: unchanged behaviour
    assert len(fake.creates("GI")) == 16 and len(fake.creates("GD")) == 1


def test_existing_record_identical_values_nothing_kept():
    fake = FakeClappia()
    sid = fake.seed("PM", FX1["project"])
    code, out = inject(fake)
    assert code == EXIT_OK and pm_edits(fake) == [] and fake.creates("PM") == []
    assert kept_lines(out) == [] and "kept=0" in out
    assert f"Project Master FX-1  -- {sid} unchanged" in out


def test_empty_fixture_value_is_never_reported_or_sent(tmp_path):
    fake = FakeClappia()
    fake.seed("PM", FX1["project"])
    code, out = inject(fake, fixture_file(tmp_path, specification=""))
    assert code == EXIT_OK and kept_lines(out) == [] and pm_edits(fake) == []


def test_missing_record_created_with_same_payload_as_before():
    fake = FakeClappia()
    code, out = inject(fake)
    assert code == EXIT_OK
    (pm,) = fake.creates("PM")
    assert pm["data"] == wrap("PM", FX1["project"])  # all 16 people_fields, exactly as before V2-04
    assert pm["data"] == to_payload(FX1["project"], LIB.settings["select_fields"]["project_master"])
    assert sorted(pm["data"]) == sorted(PEOPLE) and pm_edits(fake) == []


def test_rerun_after_people_edit_stays_hands_off():
    fake = FakeClappia()
    inject(fake)                                                   # creates the record
    fake.apps["PM"][0]["submissionFieldValues"]["volume"] = "9 MT/yr"   # someone edits it in Clappia
    n = len(fake.creates())
    for _ in range(2):
        code, out = inject(fake)
        assert code == EXIT_OK and kept_lines(out) == ["  kept Clappia value: volume"]
    assert len(fake.creates()) == n and fake.edits() == []
    assert fake.apps["PM"][0]["submissionFieldValues"]["volume"] == "9 MT/yr"


SYSTEM_IN_FIXTURE = {"traffic_light": "Green", "open_critical": 0, "last_engine_run": "2020-01-01T00:00:00Z"}


def test_system_fields_in_fixture_never_sent_on_create(tmp_path):
    fake = FakeClappia()
    code, out = inject(fake, fixture_file(tmp_path, **SYSTEM_IN_FIXTURE))
    assert code == EXIT_OK
    (pm,) = fake.creates("PM")
    assert not set(SYSTEM_IN_FIXTURE) & set(pm["data"])
    assert not set(SYSTEM) & set().union(*(set(c["data"]) for c in fake.creates()))


def test_system_fields_in_fixture_never_sent_or_reported_when_record_exists(tmp_path):
    fake = FakeClappia()
    fake.seed("PM", {**FX1["project"], "traffic_light": "Red", "open_critical": "3"})
    code, out = inject(fake, fixture_file(tmp_path, **SYSTEM_IN_FIXTURE))
    assert code == EXIT_OK and pm_edits(fake) == [] and kept_lines(out) == []
    assert fake.apps["PM"][0]["submissionFieldValues"]["traffic_light"] == ["Red"]


def test_dry_run_line_unchanged_with_system_fields_in_fixture(tmp_path):
    out = io.StringIO()
    assert run_inject(str(fixture_file(tmp_path, **SYSTEM_IN_FIXTURE)), dry_run=True,
                      env={"SG_ENABLED": "true"}, out=out) == EXIT_OK
    assert "  would upsert Project Master FX-1  -- 16 fields, match on project_code\n" in out.getvalue()


def test_unknown_fixture_field_refused_before_any_call(tmp_path):
    fake = FakeClappia()
    code, out = inject(fake, fixture_file(tmp_path, colour="red"))
    assert code == EXIT_REFUSED and fake.calls == []
    assert "fixture project field(s) ['colour']" in out


def test_pilot_guard_still_checks_fixture_when_record_exists(tmp_path):
    fake = FakeClappia()
    fake.seed("PM", FX1["project"])
    code, out = inject(fake, fixture_file(tmp_path, bd_poc_email="outsider@gmail.com"))
    assert code == EXIT_REFUSED and fake.calls == []  # stricter on purpose: refused before reading
    assert "Projects record FX-1: field 'bd_poc_email': outsider@gmail.com" in out


# ---------------------------------------------------------------- status writes system_fields only
def test_status_field_set_is_within_system_fields():
    assert set(PROJECT_FIELDS_WRITTEN) <= set(LIB.settings["system_fields"])
    check_system_fields(PROJECT_FIELDS_WRITTEN, LIB.settings)  # does not raise
    with pytest.raises(SettingsError, match=r"\['volume'\]"):
        check_system_fields(["traffic_light", "volume"], LIB.settings)


def test_status_writes_only_system_fields():
    fake = FakeClappia()
    items, _ = build_checklist(FX1["project"], FX1["sidecar"], LIB)
    fake.seed("PM", FX1["project"])
    for it in items:
        fake.seed("GI", it.to_clappia())
    fake.seed("GD", gate_decision_record(FX1["project"]))
    out = io.StringIO()
    assert run_status(project="FX-1", env=dict(ENV), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake)) == EXIT_OK
    (edit,) = pm_edits(fake)
    assert set(edit["data"]) <= set(SYSTEM) and set(edit["data"]) == set(PROJECT_FIELDS_WRITTEN)
    for f in PEOPLE:  # people fields untouched
        assert fake.apps["PM"][0]["submissionFieldValues"][f] == wrap("PM", FX1["project"])[f]


def test_status_refuses_if_settings_would_let_it_write_outside_system_fields(monkeypatch):
    lib = dataclasses.replace(LIB, settings={**LIB.settings,
                                             "system_fields": [f for f in SYSTEM if f != "last_engine_run"]})
    monkeypatch.setattr(status_mod, "load_library", lambda: lib)
    fake = FakeClappia()
    with pytest.raises(SettingsError, match=r"\['last_engine_run'\]"):
        run_status(project="FX-1", env=dict(ENV), out=io.StringIO(),
                   client_factory=lambda cfg: ClappiaClient(cfg, transport=fake))
    assert fake.calls == []  # checked before any API call
