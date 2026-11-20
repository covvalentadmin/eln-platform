"""Gate readiness (spec "Gate traffic light").

Input: Gate Items records as dicts with Clappia field names
(gate, item_id, item_class, hard_stop, item_status, superseded).

Red   : any open hard stop (any gate), or any Critical at this gate undecided or rejected
Amber : all Criticals decided; Standard items or Notes still open
Ready : everything closed -> Pass selectable; Green only after receiver accepts ownership

"Not applicable" (V2-15, from the Clappia item_status formula) closes a Standard item (ticked N/A) and a
Critical item (decision N/A), hard stops included: the named approver signs that decision. Notes have
no N/A. Closed items never appear in blockers.
"""
from __future__ import annotations

NOT_APPLICABLE = "Not applicable"
CLOSED = {
    "Standard": {"Done", NOT_APPLICABLE},
    "Critical": {"Approve", "Approve with conditions", NOT_APPLICABLE},
    "Note": {"Taken into account"},
}


def is_closed(rec: dict) -> bool:
    return rec.get("item_status") in CLOSED.get(rec.get("item_class"), set())


def evaluate(records: list, gate: str) -> dict:
    live = [r for r in records if r.get("superseded") != "Yes"]
    hard_open = [r for r in live if r.get("hard_stop") == "Yes" and not is_closed(r)]
    at_gate = [r for r in live if r.get("gate") == gate]
    crit = [r for r in at_gate if r["item_class"] == "Critical" and not is_closed(r)]
    std = [r for r in at_gate if r["item_class"] == "Standard" and not is_closed(r)]
    notes = [r for r in at_gate if r["item_class"] == "Note" and not is_closed(r)]

    crit_ids = sorted({r["item_id"] for r in crit + hard_open})
    if crit_ids:
        light = "Red"
    elif std or notes:
        light = "Amber"
    else:
        light = "Ready"

    # Each item is listed once: an open hard stop appears under HARD STOP only, not again under Critical.
    hard_ids = {r["item_id"] for r in hard_open}
    crit_only = sorted(r["item_id"] for r in crit if r["item_id"] not in hard_ids)
    parts = []
    if hard_open:
        parts.append("HARD STOP: " + ", ".join(sorted(hard_ids)))
    if crit_only:
        parts.append("Critical: " + ", ".join(crit_only))
    if std:
        parts.append("Standard: " + ", ".join(sorted(r["item_id"] for r in std)))
    if notes:
        parts.append("Notes: " + ", ".join(sorted(r["item_id"] for r in notes)))

    return {
        "traffic_light": light,
        "gate_ready": "Yes" if light == "Ready" else "No",
        "open_critical": len(crit_ids),
        "open_standard": len(std),
        "unacked_notes": len(notes),
        "blockers": " | ".join(parts) or "None",
    }
