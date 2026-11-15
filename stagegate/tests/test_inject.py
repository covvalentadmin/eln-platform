"""inject + Clappia client tests. HTTP is faked at the transport layer; real sockets are blocked."""
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from stagegate import clappia
from stagegate.clappia import ClappiaClient, ClappiaError, Config, fv, load_dotenv, norm_value, urllib_transport
from stagegate.engine import build_checklist, load_library
from stagegate.inject import EXIT_ERRORS, EXIT_OK, EXIT_REFUSED, run_inject, to_payload

FX = Path(__file__).resolve().parent.parent / "fixtures"
_SEL = load_library().settings["select_fields"]
SELECT = {"PM": set(_SEL["project_master"]), "GI": set(_SEL["gate_items"]), "GD": set(_SEL["gate_decision"])}
KEY = "sk-test-SECRET-123"
ENV = {"SG_ENABLED": "true", "CLAPPIA_API_KEY": KEY, "CLAPPIA_USER_EMAIL": "bot@example.com",
       "CLAPPIA_WORKPLACE_ID": "WP1", "SG_APP_PROJECT_MASTER": "PM", "SG_APP_GATE_ITEMS": "GI",
       "SG_APP_GATE_DECISION": "GD", "CLAPPIA_BASE_URL": "https://fake.test"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("real network call attempted in tests")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


def wrap(app, data):
    """Independent expectation of Clappia's write format: empties dropped, Select values as
    one-string lists, other lists kept, everything else a string."""
    return {k: v if isinstance(v, list) else [str(v)] if k in SELECT[app] else str(v)
            for k, v in data.items() if v is not None and v != ""}


class FakeClappia:
    """In-memory stand-in for the three endpoints, honouring EQ filters and pagination.
    Like real Clappia: rejects non-list Select values on write; stores and returns them as lists."""

    def __init__(self, page_size=None, ignore_filters=False, ignore_select_filters=False):
        self.apps = {}
        self.calls = []
        self.fail = {}  # (path, app_id) -> message
        self.n = 0
        self.page_size = page_size
        self.ignore_filters = ignore_filters
        self.ignore_select_filters = ignore_select_filters  # server drops conditions on Select fields

    def seed(self, app, data):
        """Pre-existing record, stored as Clappia would hold it (Select values as lists)."""
        self.n += 1
        sid = f"S{self.n:04d}"
        self.apps.setdefault(app, []).append({"submissionId": sid, "submissionFieldValues": wrap(app, data)})
        return sid

    def _check_select(self, app, data):
        """Write validation, as strict as live Clappia has proved to be."""
        for k, v in data.items():
            if k in SELECT.get(app, ()) and not isinstance(v, list):
                raise ClappiaError(f"HTTP 400: Error in Select value {v!r} for field {k!r}: "
                                   "value should be an array of strings")
            if not isinstance(v, (str, list)):
                raise ClappiaError(f"HTTP 400: Error in value {v!r} for field {k!r}: value should be a string")
            if v == "":
                raise ClappiaError(f"HTTP 400: Error in value '' for field {k!r}: empty value")

    @staticmethod
    def _matches(stored, value):
        return value in stored if isinstance(stored, list) else str(stored) == value

    def edits(self):
        return [b for p, b in self.calls if p.endswith("/edit")]

    def creates(self, app=None):
        return [b for p, b in self.calls if p.endswith("/create") and (app is None or b["appId"] == app)]

    def __call__(self, url, headers, body, timeout):
        assert url.startswith("https://fake.test/submissions/")
        assert headers["x-api-key"] == KEY
        assert body["workplaceId"] == "WP1" and body["requestingUserEmailAddress"] == "bot@example.com"
        path = url[len("https://fake.test"):]
        self.calls.append((path, json.loads(json.dumps(body))))
        if (path, body["appId"]) in self.fail:
            raise ClappiaError(self.fail[(path, body["appId"])])
        recs = self.apps.setdefault(body["appId"], [])
        if path == "/submissions/create":
            self._check_select(body["appId"], body["data"])
            self.n += 1
            sid = f"S{self.n:04d}"
            recs.append({"submissionId": sid, "submissionFieldValues": dict(body["data"])})
            return {"submissionId": sid}
        if path == "/submissions/edit":
            self._check_select(body["appId"], body["data"])
            rec = next(r for r in recs if r["submissionId"] == body["submissionId"])
            rec["submissionFieldValues"].update(body["data"])
            return {}
        if path == "/submissions/getSubmissions":
            conds = [] if self.ignore_filters else [
                c for q in (body.get("filters") or {}).get("queries", []) for c in q["conditions"]
                if not (self.ignore_select_filters and c["key"] in SELECT.get(body["appId"], ()))]
            hits = [r for r in recs if all(self._matches(r["submissionFieldValues"].get(c["key"]), c["value"])
                                           for c in conds)]
            if body.get("lastSubmissionId"):
                ids = [r["submissionId"] for r in hits]
                hits = hits[ids.index(body["lastSubmissionId"]) + 1:]
            page = hits[: self.page_size or body["pageSize"]]
            return {"submissions": page, "metadata": {"count": len(page)},
                    "lastSubmissionId": page[-1]["submissionId"] if page else None}
        raise AssertionError(path)


def run(fake, fixture="FX-1.json", env=ENV, **kw):
    out = io.StringIO()
    code = run_inject(str(FX / fixture), env=dict(env), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=fake), **kw)
    return code, out.getvalue()


def expected_items(fixture="FX-1.json"):
    d = json.load(open(FX / fixture, encoding="utf-8"))
    return d["project"], build_checklist(d["project"], d["sidecar"], load_library())[0]


# ---------------------------------------------------------------- guardrails
def test_disabled_exits_before_anything():
    fake = FakeClappia()
    code, out = run(fake, env={**ENV, "SG_ENABLED": "false"})
    assert code == EXIT_REFUSED and "disabled" in out and fake.calls == []
    code, _ = run(fake, env={k: v for k, v in ENV.items() if k != "SG_ENABLED"})
    assert code == EXIT_REFUSED and fake.calls == []


def test_non_fx_project_refused_unless_allow_live(tmp_path):
    d = json.load(open(FX / "FX-1.json", encoding="utf-8"))
    d["project"]["project_code"] = d["sidecar"]["project_code"] = "CV-101"
    p = tmp_path / "live.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    fake = FakeClappia()
    out = io.StringIO()
    assert run_inject(str(p), env=dict(ENV), out=out, client_factory=lambda c: ClappiaClient(c, fake)) == EXIT_REFUSED
    assert "Refusing" in out.getvalue() and fake.calls == []
    out = io.StringIO()
    assert run_inject(str(p), dry_run=True, allow_live=True, env=dict(ENV), out=out) == EXIT_OK


def test_dry_run_makes_no_calls_and_needs_no_key():
    def factory(cfg):
        raise AssertionError("client built in dry run")
    out = io.StringIO()
    env = {"SG_ENABLED": "true"}
    assert run_inject(str(FX / "FX-1.json"), dry_run=True, env=env, out=out, client_factory=factory) == EXIT_OK
    _, items = expected_items()
    text = out.getvalue()
    assert text.count("would create") == len(items) + 1 + 1  # items + decision + summary line
    assert "DRY RUN" in text


def test_live_run_refuses_without_key_or_user():
    for k in ("CLAPPIA_API_KEY", "CLAPPIA_USER_EMAIL"):
        fake = FakeClappia()
        code, out = run(fake, env={**ENV, k: ""})
        assert code == EXIT_REFUSED and k in out and fake.calls == []


# ---------------------------------------------------------------- happy path + idempotency
def test_fresh_inject_creates_everything():
    fake = FakeClappia()
    code, out = run(fake)
    project, items = expected_items()
    assert code == EXIT_OK
    assert fake.creates("PM") == [{"appId": "PM", "workplaceId": "WP1",
                                   "requestingUserEmailAddress": "bot@example.com", "data": wrap("PM", project)}]
    assert [c["data"] for c in fake.creates("GI")] == [wrap("GI", i.to_clappia()) for i in items]
    (dec,) = fake.creates("GD")
    assert dec["data"] == {"project_code": "FX-1", "gate": ["G1"], "receiving_poc_email": project["rd_lead_email"]}
    assert f"created={len(items) + 2}" in out and "skipped=0" in out and "error=0" in out


def test_fresh_run_creates_18_records_with_select_values_as_lists():
    fake = FakeClappia()
    code, _ = run(fake)
    creates = fake.creates()
    assert code == EXIT_OK and len(creates) == 18  # 1 Project Master + 16 Gate Items + 1 Gate Decision
    for c in creates:
        for k, v in c["data"].items():
            if k in SELECT[c["appId"]]:
                assert isinstance(v, list) and len(v) == 1 and isinstance(v[0], str), (c["appId"], k, v)
            else:
                assert isinstance(v, str) and v != "", (c["appId"], k, v)
    pm = fake.creates("PM")[0]["data"]
    assert pm["end_use"] == ["Specialty / industrial"] and pm["incoterms"] == ["CIF"]
    assert pm["transit_temperature"] == ["Ambient"] and pm["target_market"] == "EU"
    gi = fake.creates("GI")[0]["data"]
    assert gi["gate"] == ["G1"] and gi["hard_stop"] == ["No"] and gi["superseded"] == ["No"]
    assert isinstance(gi["idempotency_key"], str)


def test_fresh_run_numbers_as_strings_and_empties_dropped():
    fake = FakeClappia()
    code, _ = run(fake)
    assert code == EXIT_OK
    assert fake.creates("PM")[0]["data"]["target_price_usd_kg"] == "85"
    by_id = {c["data"]["item_id"]: c["data"] for c in fake.creates("GI")}
    assert by_id["DF-L5"]["kickoff_score"] == "3"
    core = [d for d in by_id.values() if d["source"] == ["Core template"]]
    assert len(core) == 13
    for d in core:
        assert "approver_email" not in d and "kickoff_finding" not in d and "kickoff_score" not in d, d["item_id"]
    assert all(v != "" for c in fake.creates() for v in c["data"].values())


def test_rerun_with_list_valued_reads_creates_and_edits_nothing():
    fake = FakeClappia()
    run(fake)
    # stored records really are list-valued for Select fields
    assert fake.apps["GI"][0]["submissionFieldValues"]["gate"] == ["G1"]
    assert fake.apps["PM"][0]["submissionFieldValues"]["end_use"] == ["Specialty / industrial"]
    before = len(fake.creates())
    code, out = run(fake)
    _, items = expected_items()
    assert code == EXIT_OK and len(fake.creates()) == before and fake.edits() == []
    assert f"skipped={len(items) + 2}" in out and "created=0" in out and "updated=0" in out


def test_select_field_change_edits_as_list():
    fake = FakeClappia()
    project, _ = expected_items()
    sid = fake.seed("PM", {**project, "incoterms": "FOB"})
    code, _ = run(fake)
    assert code == EXIT_OK
    assert [e["data"] for e in fake.edits()] == [{"incoterms": ["CIF"]}] and fake.edits()[0]["submissionId"] == sid


def test_existing_g1_decision_found_when_server_ignores_select_filters():
    fake = FakeClappia(ignore_select_filters=True)
    fake.seed("GD", {"project_code": "FX-1", "gate": "G2", "receiving_poc_email": "x@y"})
    g1 = fake.seed("GD", {"project_code": "FX-1", "gate": "G1", "receiving_poc_email": "x@y"})
    fake.seed("GD", {"project_code": "FX-OTHER", "gate": "G1", "receiving_poc_email": "x@y"})
    code, out = run(fake)
    assert code == EXIT_OK and fake.creates("GD") == []
    assert f"skipped      Gate Decision FX-1|G1  -- {g1} already exists" in out
    gd_reads = [b for p, b in fake.calls if p.endswith("getSubmissions") and b["appId"] == "GD"]
    assert [c["key"] for c in gd_reads[0]["filters"]["queries"][0]["conditions"]] == ["project_code"]
    before = len(fake.creates())
    code, _ = run(fake)  # full re-run against the same server: nothing new at all
    assert code == EXIT_OK and len(fake.creates()) == before and fake.edits() == []


def test_client_side_recheck_is_authoritative():
    fake = FakeClappia(ignore_filters=True)  # server returns everything, filters ignored
    project, items = expected_items()
    fake.seed("PM", {**project, "project_code": "FX-OTHER"})
    fake.seed("GD", {"project_code": "FX-1", "gate": "G2", "receiving_poc_email": "x@y"})
    fake.seed("GD", {"project_code": "FX-OTHER", "gate": "G1", "receiving_poc_email": "x@y"})
    fake.seed("GI", {**items[0].to_clappia(), "project_code": "FX-OTHER", "idempotency_key": items[1].idempotency_key})
    code, _ = run(fake)
    assert code == EXIT_OK
    assert len(fake.creates("PM")) == 1 and fake.edits() == []
    assert len(fake.creates("GI")) == len(items)
    assert [c["data"]["gate"] for c in fake.creates("GD")] == [["G1"]]


def test_fake_rejects_plain_select_value():
    fake = FakeClappia()
    c = ClappiaClient(Config.from_env(ENV), transport=fake)
    with pytest.raises(ClappiaError, match="array of strings"):
        c.create_submission("GI", {"gate": "G1"})


def test_fake_rejects_numbers_and_empty_strings():
    c = ClappiaClient(Config.from_env(ENV), transport=FakeClappia())
    with pytest.raises(ClappiaError, match="should be a string"):
        c.create_submission("PM", {"target_price_usd_kg": 85})
    with pytest.raises(ClappiaError, match="empty value"):
        c.create_submission("GI", {"approver_email": ""})


def test_to_payload_and_norm_value():
    data = {"gate": "G1", "item_class": "", "hard_stop": None, "source": ["Core"], "item_title": "x",
            "n": 3, "price": 85.5, "flag": True, "tags": ["a", "b"]}
    assert to_payload(data, ["gate", "item_class", "hard_stop", "source"]) == {
        "gate": ["G1"], "source": ["Core"], "item_title": "x", "n": "3", "price": "85.5", "flag": "True",
        "tags": ["a", "b"]}
    assert to_payload({"gate": "G1", "e": ""}, None) == {"gate": "G1"}
    assert norm_value(["a", 1]) == "a, 1" and norm_value(85) == "85" and norm_value("G1") == "G1"
    assert fv({"submissionFieldValues": {"gate": ["G1"], "kickoff_score": 3}}) == {"gate": "G1", "kickoff_score": "3"}


def test_only_missing_items_created():
    fake = FakeClappia()
    project, items = expected_items()
    for it in items[:3]:
        fake.seed("GI", it.to_clappia())
    fake.seed("GI", {**items[3].to_clappia(), "project_code": "FX-OTHER"})  # other project: ignored
    code, _ = run(fake)
    created = [c["data"]["idempotency_key"] for c in fake.creates("GI")]
    assert code == EXIT_OK and created == [i.idempotency_key for i in items[3:]]


def test_project_master_upsert_edits_only_changed_fields():
    fake = FakeClappia()
    project, _ = expected_items()
    sid = fake.seed("PM", {**project, "volume": "1 MT/yr"})
    code, out = run(fake)
    edits = [b for p, b in fake.calls if p.endswith("/edit")]
    assert code == EXIT_OK and not fake.creates("PM")
    assert edits == [{"appId": "PM", "workplaceId": "WP1", "requestingUserEmailAddress": "bot@example.com",
                      "submissionId": sid, "data": {"volume": project["volume"]}}]
    assert "updated" in out


def test_existing_decision_not_duplicated():
    fake = FakeClappia()
    fake.seed("GD", {"project_code": "FX-1", "gate": "G1", "receiving_poc_email": "x@y"})
    run(fake)
    assert fake.creates("GD") == []


def test_pagination_follows_last_submission_id(monkeypatch):
    fake = FakeClappia(page_size=2)
    _, items = expected_items()
    for it in items:
        fake.seed("GI", it.to_clappia())
    monkeypatch.setattr(clappia, "PAGE_SIZE", 2)
    code, _ = run(fake)
    gets = [b for p, b in fake.calls if p.endswith("getSubmissions") and b["appId"] == "GI"]
    assert code == EXIT_OK and fake.creates("GI") == []
    assert len(gets) >= len(items) // 2 and "lastSubmissionId" in gets[1]
    cond = gets[0]["filters"]["queries"][0]["conditions"][0]
    assert cond == {"operator": "EQ", "filterKeyType": "CUSTOM", "key": "project_code", "value": "FX-1"}


# ---------------------------------------------------------------- failures
def test_gate_items_read_failure_creates_no_items():
    fake = FakeClappia()
    fake.fail[("/submissions/getSubmissions", "GI")] = "boom"
    code, out = run(fake)
    assert code == EXIT_ERRORS and fake.creates("GI") == [] and "none created" in out


def test_project_master_failure_aborts():
    fake = FakeClappia()
    fake.fail[("/submissions/getSubmissions", "PM")] = "boom"
    code, out = run(fake)
    assert code == EXIT_ERRORS and fake.creates() == [] and "Aborting" in out


def test_duplicate_project_master_aborts():
    fake = FakeClappia()
    project, _ = expected_items()
    fake.seed("PM", project)
    fake.seed("PM", project)
    code, _ = run(fake)
    assert code == EXIT_ERRORS and fake.creates() == []


def test_item_create_error_counted_and_others_continue():
    fake = FakeClappia()
    _, items = expected_items()
    real = fake.__call__
    calls = {"n": 0}

    def flaky(url, headers, body, timeout):
        if url.endswith("/create") and body["appId"] == "GI":
            calls["n"] += 1
            if calls["n"] == 2:
                raise ClappiaError("422 bad field")
        return real(url, headers, body, timeout)

    out = io.StringIO()
    code = run_inject(str(FX / "FX-1.json"), env=dict(ENV), out=out,
                      client_factory=lambda cfg: ClappiaClient(cfg, transport=flaky))
    assert code == EXIT_ERRORS and "error=1" in out.getvalue()
    assert len(fake.creates("GI")) == len(items) - 1


# ---------------------------------------------------------------- client / config
def test_api_key_never_in_output_or_repr():
    fake = FakeClappia()
    fake.fail[("/submissions/getSubmissions", "PM")] = "denied"
    _, out = run(fake)
    cfg = Config.from_env(ENV)
    assert KEY not in out and KEY not in repr(cfg) and KEY not in repr(ClappiaClient(cfg, fake))


def test_api_error_payload_raises():
    cfg = Config.from_env(ENV)
    c = ClappiaClient(cfg, transport=lambda *a: {"error": "Error for appId: GI in creating submission"})
    with pytest.raises(ClappiaError, match="creating submission"):
        c.create_submission("GI", {})


def test_urllib_transport_maps_http_error_without_key(monkeypatch):
    def fake_open(req, timeout):
        assert req.get_header("X-api-key") == KEY and req.get_method() == "POST"
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}'))
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    with pytest.raises(ClappiaError) as ei:
        urllib_transport("https://fake.test/submissions/create", {"x-api-key": KEY}, {}, 5)
    assert "401" in str(ei.value) and KEY not in str(ei.value)


def test_load_dotenv_parses_and_never_overrides(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# c\n\nA=1\nB="two words"\nexport C=\'3\'\nD=keep\nbad line\n', encoding="utf-8")
    env = {"D": "existing"}
    load_dotenv(p, env)
    assert env == {"A": "1", "B": "two words", "C": "3", "D": "existing"}
    load_dotenv(tmp_path / "missing", env)  # no error


def test_config_defaults_safe():
    cfg = Config.from_env({})
    assert not cfg.enabled and cfg.api_key == "" and cfg.base_url == clappia.DEFAULT_BASE_URL
    assert (cfg.app_project_master, cfg.app_gate_items, cfg.app_gate_decision) == ("SGT708875", "SGT584136", "SGT087528")
    assert set(cfg.missing_for_live()) == {"CLAPPIA_API_KEY", "CLAPPIA_USER_EMAIL"}
