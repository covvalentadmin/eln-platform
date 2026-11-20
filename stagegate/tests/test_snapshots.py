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


@pytest.mark.parametrize("name,kind,fn", CASES, ids=[f"{n}-{k}" for n, k, _ in CASES])
def test_snapshot(name, kind, fn):
    path = SNAP / f"{name}.{kind}.txt"
    got = fn(name)
    if os.environ.get("SNAPSHOT_UPDATE") == "1":
        SNAP.mkdir(exist_ok=True)
        path.write_bytes(got.encode("utf-8"))
    assert path.is_file(), f"missing snapshot {path.name}; generate with SNAPSHOT_UPDATE=1"
    assert got.encode("utf-8") == path.read_bytes(), f"{path.name} changed"
