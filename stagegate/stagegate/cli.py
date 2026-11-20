"""stagegate CLI — v0.1. `preview` (offline dry run), `inject` (Clappia write), `status` (traffic light)."""
import argparse
import dataclasses
import json
import sys

from stagegate.engine import build_checklist, load_library


def preview_core_gate(path: str, gate: str) -> int:
    """Offline: list one gate's core-template items for a fixture, routed through the normal engine
    path, whether or not that gate is active. Nothing is injected or sent anywhere."""
    lib = load_library()
    if gate not in lib.cores:
        print(f"no core template for {gate}; loaded: {', '.join(sorted(lib.cores))}", file=sys.stderr)
        return 2
    data = json.load(open(path, encoding="utf-8"))
    items, _ = build_checklist(data["project"], data["sidecar"], dataclasses.replace(lib, core=lib.cores[gate]))
    items = [i for i in items if i.source == "Core template" and i.gate == gate]
    order = {c["id"]: n for n, c in enumerate(lib.cores[gate])}
    items.sort(key=lambda i: order[i.item_id])  # template order
    print(f"{'GATE':4} {'ITEM':7} {'CLASS':8} {'HS':2} {'CHECKPOINT':14} {'OWNER':34} APPROVER/ACK")
    for i in items:
        std = i.item_class == "Standard"
        owner = i.owner_email + (" [fallback]" if std and i.role_fallback else "")
        who = "" if std else i.approver_email + (" [fallback]" if i.role_fallback else "")
        print(f"{i.gate:4} {i.item_id:7} {i.item_class:8} {'Y' if i.hard_stop else '-':2} {i.checkpoint:14} "
              f"{owner:34} {who}".rstrip())
    active = lib.settings.get("active_core_gates", ["G1"])
    print(f"\n{gate} core template: {len(items)} items; "
          f"{'ACTIVE' if gate in active else 'not active'} (active_core_gates: {', '.join(active)})")
    return 0


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
    pv.add_argument("--core-gate", metavar="GATE",
                    help="List only this gate's core-template items (e.g. G2), even if the gate is not active")
    ij = sub.add_parser("inject", help="Write a fixture's G1 checklist to the SG-TEST Clappia apps (idempotent)")
    ij.add_argument("fixture")
    ij.add_argument("--dry-run", action="store_true", help="Show the plan; make no API calls at all")
    ij.add_argument("--allow-live", action="store_true", help="Allow project codes that don't start with FX-")
    st = sub.add_parser("status", help="Compute the G1 traffic light from Clappia and write it back")
    st.add_argument("fixture", nargs="?", help="Fixture JSON (project_code is read from it)")
    st.add_argument("--project", help="Project code, e.g. FX-1 (instead of a fixture)")
    st.add_argument("--dry-run", action="store_true", help="Simulate from the fixture; make no API calls at all")
    st.add_argument("--allow-live", action="store_true", help="Allow project codes that don't start with FX-")
    a = p.parse_args(argv)
    if a.cmd == "status":
        if bool(a.fixture) == bool(a.project):
            st.error("give exactly one of: a fixture path, or --project")
        from stagegate.status import run_status
        return run_status(a.fixture, a.project, dry_run=a.dry_run, allow_live=a.allow_live)
    if a.cmd == "inject":
        from stagegate.inject import run_inject
        return run_inject(a.fixture, dry_run=a.dry_run, allow_live=a.allow_live)
    if a.core_gate:
        return preview_core_gate(a.fixture, a.core_gate)
    return preview(a.fixture)


if __name__ == "__main__":
    sys.exit(main())
