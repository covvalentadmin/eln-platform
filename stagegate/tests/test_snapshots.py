"""Snapshot guard: G1 behaviour must not change.

Exact stdout of `preview fixtures/FX-n.json` and `inject fixtures/FX-n.json --dry-run` for FX-1..FX-4,
compared byte for byte with tests/snapshots/. No timestamps appear in either output, so nothing is
normalised. Both run offline: preview never touches Clappia, and inject --dry-run makes no API calls
(the env is passed explicitly, so .env is never read).

Regenerate only on purpose:  $env:SNAPSHOT_UPDATE = "1"; .venv\\Scripts\\python.exe -m pytest tests/test_snapshots.py
"""
import contextlib
import io
import os
from pathlib import Path

import pytest

from stagegate.cli import main as cli_main
from stagegate.inject import run_inject

ROOT = Path(__file__).resolve().parent.parent
SNAP = Path(__file__).resolve().parent / "snapshots"
FIXTURES = ["FX-1", "FX-2", "FX-3", "FX-4"]


def preview_output(name: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli_main(["preview", str(ROOT / "fixtures" / f"{name}.json")]) == 0
    return buf.getvalue()


def inject_dry_run_output(name: str) -> str:
    buf = io.StringIO()
    code = run_inject(str(ROOT / "fixtures" / f"{name}.json"), dry_run=True,
                      env={"SG_ENABLED": "true"}, out=buf,
                      client_factory=lambda cfg: pytest.fail("dry run built a Clappia client"))
    assert code == 0
    return buf.getvalue()


CASES = [(n, kind, fn) for n in FIXTURES
         for kind, fn in (("preview", preview_output), ("inject-dry-run", inject_dry_run_output))]


def clappia_payloads(name: str) -> dict:
    """Exactly what inject would send for a fixture: Projects record, every Gate Item, the Decision."""
    import json
    from stagegate.engine import build_checklist, load_library
    from stagegate.inject import clappia_project_fields, gate_decision_record, to_payload
    lib = load_library()
    sel = lib.settings["select_fields"]
    d = json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    items, _ = build_checklist(d["project"], d["sidecar"], lib)
    return {"project": to_payload(clappia_project_fields(d["project"], lib.settings), sel["project_master"]),
            "items": [to_payload(i.to_clappia(), sel["gate_items"]) for i in items],
            "decision": to_payload(gate_decision_record(d["project"]), sel["gate_decision"])}


@pytest.mark.parametrize("name", FIXTURES)
def test_clappia_payloads_unchanged(name):
    """Everything inject would send for FX-n (Projects record, every Gate Item incl. the "Owner: <role>
    (fallback: role holder not set)" labels, the Decision), pinned by SHA-256 of its canonical JSON as
    captured before V2-03. To inspect a mismatch, dump clappia_payloads(name) and compare by hand."""
    import hashlib
    import json
    want = json.loads((SNAP / "FX-payloads.sha256.json").read_text(encoding="utf-8"))[name]
    canon = json.dumps(clappia_payloads(name), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == want, f"{name} Clappia payloads changed"


@pytest.mark.parametrize("name,kind,fn", CASES, ids=[f"{n}-{k}" for n, k, _ in CASES])
def test_snapshot(name, kind, fn):
    path = SNAP / f"{name}.{kind}.txt"
    got = fn(name)
    if os.environ.get("SNAPSHOT_UPDATE") == "1":
        SNAP.mkdir(exist_ok=True)
        path.write_bytes(got.encode("utf-8"))
    assert path.is_file(), f"missing snapshot {path.name}; generate with SNAPSHOT_UPDATE=1"
    assert got.encode("utf-8") == path.read_bytes(), f"{path.name} changed"
