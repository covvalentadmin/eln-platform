"""stagegate CLI — v0.1. Day 1: `preview` (offline dry run). Day 3 adds `inject`, Day 4 `status`."""
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
    a = p.parse_args(argv)
    return preview(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
