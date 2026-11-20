"""Pilot-users-only guard (V2-03).

When settings.yaml enforce_pilot_allowlist is true, every email that inject or status would write
must be on pilot_allowlist: Projects record fields, every Gate Item's owner_email and approver_email,
and the Decision record's receiving_poc_email. Callers check BEFORE any API call (or, for
`status --project`, after its reads and before any write) and send nothing if anything fails.
Comparison is case-insensitive; a field may hold several addresses (comma/semicolon separated).
"""
from __future__ import annotations

import re

_SPLIT = re.compile(r"[,;\s]+")


def enforced(settings: dict) -> bool:
    return settings.get("enforce_pilot_allowlist") is True


def addresses(value) -> list:
    """Email addresses in a field value (empty list for non-email values)."""
    if not isinstance(value, str) or "@" not in value:
        return []
    return [a for a in _SPLIT.split(value.strip()) if "@" in a]


def _violations(entries, settings) -> list:
    """entries: (where, field, value). One message per address not on the allowlist."""
    ok = {a.strip().lower() for a in settings.get("pilot_allowlist") or []}
    return [f"{where}: field '{fld}': {a}"
            for where, fld, value in entries for a in addresses(value) if a.lower() not in ok]


def planned_violations(pc: str, project_fields: dict, items: list, decision: dict, gate: str,
                       settings: dict) -> list:
    """Emails an inject run would write, from the fixture (no API call needed)."""
    if not enforced(settings):
        return []
    entries = [("Projects record " + pc, k, v) for k, v in project_fields.items()]
    for it in items:
        entries += [(f"Gate Item {it.idempotency_key}", "owner_email", it.owner_email),
                    (f"Gate Item {it.idempotency_key}", "approver_email", it.approver_email)]
    entries.append((f"Gate Decision {pc}|{gate}", "receiving_poc_email", decision.get("receiving_poc_email", "")))
    return _violations(entries, settings)


def record_violations(pc: str, project_records: list, item_records: list, decision_records: list,
                      gate: str, settings: dict) -> list:
    """Emails held in records read back from Clappia (normalised field dicts)."""
    if not enforced(settings):
        return []
    entries = [("Projects record " + pc, k, v) for rec in project_records for k, v in rec.items()]
    for rec in item_records:
        where = f"Gate Item {rec.get('idempotency_key') or rec.get('item_id', '?')}"
        entries += [(where, "owner_email", rec.get("owner_email", "")),
                    (where, "approver_email", rec.get("approver_email", ""))]
    entries += [(f"Gate Decision {pc}|{gate}", "receiving_poc_email", rec.get("receiving_poc_email", ""))
                for rec in decision_records]
    return _violations(entries, settings)


def refuse(cmd: str, violations: list, out, nothing: str = "Nothing sent") -> None:
    print(f"{cmd} refused: {len(violations)} email(s) not on settings.yaml pilot_allowlist "
          f"(enforce_pilot_allowlist: true). {nothing}.", file=out)
    for v in violations:
        print(f"  {v}", file=out)
