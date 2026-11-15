"""stagegate CLI — v0.1. `preview` (offline dry run), `inject` (Clappia write). Day 4 adds `status`."""
import argparse
import json
import sys

from stagegate.engine import build_checklist, load_library


def preview(path: str) -> int:
    data = json.load(open(path, encoding="utf-8"))
    items, log = build_checklist(data["project"], data["sidecar"], load_library())
    print(f"{'GATE':4} {'ITEM':10} {'CLASS':8} {'HS':2} {'SRC':10} APPROVER/ACK")
    for i in items:
        src = {"Core template": "core", "Kickoff register": "kickoff", "Mandatory item": "mandatory",
               "Unmapped kickoff row": "UNMAPPED"}.get(i.source, i.source)
        who = i.approver_email if i.item_class != "Standard" else ""
        print(f"{i.gate:4} {i.item_id:10} {i.item_class:8} {'Y' if i.hard_stop else '-':2} {src:10} {who}"
              + ("  [fallback]" if i.role_fallback and who else ""))
    print("\nimport log:", json.dumps(log))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stagegate")
    sub = p.add_subparsers(dest="cmd", required=True)
    pv = sub.add_parser("preview", help="Dry-run a {project, sidecar} JSON; no Clappia calls")
    pv.add_argument("fixture")
    ij = sub.add_parser("inject", help="Write a fixture's G1 checklist to the SG-TEST Clappia apps (idempotent)")
    ij.add_argument("fixture")
    ij.add_argument("--dry-run", action="store_true", help="Show the plan; make no API calls at all")
    ij.add_argument("--allow-live", action="store_true", help="Allow project codes that don't start with FX-")
    a = p.parse_args(argv)
    if a.cmd == "inject":
        from stagegate.inject import run_inject
        return run_inject(a.fixture, dry_run=a.dry_run, allow_live=a.allow_live)
    return preview(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
