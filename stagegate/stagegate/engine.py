"""Stage-gate MVP v0.1 classification engine.

Pure functions: (project, sidecar, library) -> checklist items + import log.
No I/O beyond loading YAML; the Clappia client (Day 3) consumes Item.to_clappia().

Rules implemented (spec "Classification rules"):
  score 5 -> Critical, hard stop, always at G1
  score 4 -> Critical at the rule's target gate
  score 3 -> Note
  score 1-2 -> never reach a checklist (logged as skipped)
  learning_match raises Note -> Critical; nothing ever lowers a class
  mandatory item: breach -> Critical, no breach -> Note
  rows that map to no loaded rule are never dropped: they become generic items
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RANK = {"Standard": 0, "Note": 1, "Critical": 2}
STAGES = {"Sourcing", "R&D", "Scaleup", "Regulatory", "Logistics"}
CONFIDENCE = {"Low", "Medium", "High"}


# ---------------------------------------------------------------- library
@dataclass(frozen=True)
class Library:
    core: list
    rules: dict
    learning_to_rule: dict
    deferred: dict
    settings: dict


def load_library(data_dir: Path = DATA_DIR) -> Library:
    def y(name):
        with open(data_dir / name, encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    core = y("g1_core.yaml")["items"]
    rules = {r["id"]: r for r in y("flag_rules_g1.yaml")["rules"]}
    l2r = {lid: r["id"] for r in rules.values() for lid in r.get("learning_ids", [])}
    deferred = y("learning_map_deferred.yaml")["deferred"]
    overlap = set(l2r) & set(deferred)
    if overlap:
        raise ValueError(f"learning IDs mapped twice: {sorted(overlap)}")
    return Library(core, rules, l2r, deferred, y("settings.yaml"))


# ---------------------------------------------------------------- model
@dataclass
class Item:
    project_code: str
    gate: str
    item_id: str
    source: str
    item_title: str
    acceptance_criterion: str
    item_class: str
    hard_stop: bool = False
    kickoff_score: Optional[int] = None
    findings: list = field(default_factory=list)
    owner_email: str = ""
    approver_role: str = ""
    approver_email: str = ""
    role_fallback: bool = False

    @property
    def idempotency_key(self) -> str:
        return f"{self.project_code}|{self.gate}|{self.item_id}"

    def to_clappia(self) -> dict:
        """Field names match SG-TEST · Gate Items (SGT584136)."""
        d = {
            "project_code": self.project_code,
            "gate": self.gate,
            "item_id": self.item_id,
            "source": self.source,
            "item_title": self.item_title,
            "acceptance_criterion": self.acceptance_criterion,
            "item_class": self.item_class,
            "hard_stop": "Yes" if self.hard_stop else "No",
            "kickoff_finding": " || ".join(self.findings),
            "owner_email": self.owner_email,
            "approver_role": self.approver_role + (" (fallback: role holder not set)" if self.role_fallback else ""),
            "approver_email": self.approver_email,
            "idempotency_key": self.idempotency_key,
            "superseded": "No",
        }
        if self.kickoff_score is not None:
            d["kickoff_score"] = self.kickoff_score
        return d


# ---------------------------------------------------------------- helpers
def class_from_score(score: int) -> Optional[str]:
    if score >= 4:
        return "Critical"
    if score == 3:
        return "Note"
    return None


def raise_only(current: str, candidate: str) -> str:
    return candidate if RANK[candidate] > RANK[current] else current


def _short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:6].upper()


def validate_sidecar(sc: dict) -> list:
    """Field-level errors; empty list means valid."""
    errs = []
    for k in ("project_code", "run_id", "run_date"):
        if not isinstance(sc.get(k), str) or not sc.get(k):
            errs.append(f"{k}: required non-empty string")
    rows = sc.get("rows")
    if not isinstance(rows, list):
        return errs + ["rows: required list"]
    for i, r in enumerate(rows):
        p = f"rows[{i}]"
        if r.get("stage") not in STAGES:
            errs.append(f"{p}.stage: must be one of {sorted(STAGES)}")
        if not r.get("risk"):
            errs.append(f"{p}.risk: required")
        s = r.get("score")
        if not isinstance(s, int) or isinstance(s, bool) or not 1 <= s <= 5:
            errs.append(f"{p}.score: integer 1-5 required")
        if r.get("confidence") not in CONFIDENCE:
            errs.append(f"{p}.confidence: must be one of {sorted(CONFIDENCE)}")
    for i, m in enumerate(sc.get("mandatory", []) or []):
        if not m.get("rule_id"):
            errs.append(f"mandatory[{i}].rule_id: required")
        if not isinstance(m.get("breach"), bool):
            errs.append(f"mandatory[{i}].breach: boolean required")
    return errs


class _Resolver:
    def __init__(self, project: dict, settings: dict):
        self.p, self.s = project, settings

    def email(self, role: str) -> tuple:
        f = self.s["role_fields"].get(role)
        if f and self.p.get(f):
            return self.p[f], False
        fb = self.s["role_fallbacks"].get(role) or "founder_approver_email"
        return self.p.get(fb, ""), True

    def receiver(self, gate: str) -> tuple:
        f = self.s["receiving_poc_field"].get(gate)
        if f and self.p.get(f):
            return self.p[f], False
        return self.p.get("rd_lead_email", ""), True


# ---------------------------------------------------------------- engine
def build_checklist(project: dict, sidecar: dict, lib: Library) -> tuple:
    """Return (items sorted by gate/item_id, import_log). Raises ValueError on invalid sidecar."""
    errs = validate_sidecar(sidecar)
    if errs:
        raise ValueError("invalid sidecar: " + "; ".join(errs))
    pc = sidecar["project_code"]
    if project.get("project_code") and project["project_code"] != pc:
        raise ValueError(f"project_code mismatch: project {project['project_code']} vs sidecar {pc}")

    res = _Resolver(project, lib.settings)
    bucket: dict = {}
    log = {"run_id": sidecar["run_id"], "rows_read": len(sidecar["rows"]),
           "rows_imported": 0, "rows_skipped_low_score": 0,
           "rows_unmapped": 0, "rows_deferred_rule": 0, "mandatory_read": 0}

    def put(item: Item):
        key = (item.gate, item.item_id)
        if key not in bucket:
            bucket[key] = item
            return
        cur = bucket[key]
        cur.item_class = raise_only(cur.item_class, item.item_class)
        cur.hard_stop = cur.hard_stop or item.hard_stop
        if item.kickoff_score is not None:
            cur.kickoff_score = max(cur.kickoff_score or 0, item.kickoff_score)
        cur.findings += [f for f in item.findings if f not in cur.findings]

    # 1. kickoff register rows
    for r in sidecar["rows"]:
        score = r["score"]
        cls = class_from_score(score)
        if cls is None:
            log["rows_skipped_low_score"] += 1
            continue
        log["rows_imported"] += 1
        if r.get("learning_match"):
            cls = raise_only(cls, "Critical")
        lid = r.get("learning_id")
        finding = f"[{r['stage']}] {r['risk']} (score {score}, {r['confidence']}" + (f", {lid})" if lid else ")")

        rule = lib.rules.get(r.get("rule_id") or "") or lib.rules.get(lib.learning_to_rule.get(lid or "", ""))
        if rule:
            gate = "G1" if score == 5 else rule["gates"][0]
            put(Item(pc, gate, rule["id"], "Kickoff register", rule["item"], rule["criterion"], cls,
                     hard_stop=(score == 5) or (rule["hard_stop"] and cls == "Critical"),
                     kickoff_score=score, findings=[finding]))
            continue

        d = lib.deferred.get(lid or "")
        if d:
            log["rows_deferred_rule"] += 1
            gate = "G1" if score == 5 else d["gate"]
            put(Item(pc, gate, d["rule"], "Kickoff register",
                     f"Kickoff finding (rule {d['rule']} loads in a later release): {r['risk']}",
                     f"Resolve per {d['rule']} in the spec; full criterion loads with the rule", cls,
                     hard_stop=(score == 5), kickoff_score=score, findings=[finding]))
        else:
            log["rows_unmapped"] += 1
            put(Item(pc, "G1", f"KO-{_short_hash(r['stage'], r['risk'])}", "Unmapped kickoff row",
                     f"Kickoff finding: {r['risk']}",
                     "PM maps this finding to a flag rule and sets an objective acceptance criterion", cls,
                     hard_stop=(score == 5), kickoff_score=score, findings=[finding]))

    # 2. mandatory items
    for m in sidecar.get("mandatory", []) or []:
        log["mandatory_read"] += 1
        cls = "Critical" if m["breach"] else "Note"
        finding = f"[Mandatory] {m['rule_id']} {'breach' if m['breach'] else 'information'}" + (f": {m['detail']}" if m.get("detail") else "")
        rule = lib.rules.get(m["rule_id"])
        if rule:
            put(Item(pc, rule["gates"][0], rule["id"], "Mandatory item", rule["item"], rule["criterion"], cls,
                     hard_stop=rule["hard_stop"] and cls == "Critical", findings=[finding]))
        else:
            put(Item(pc, "G1", f"MI-{m['rule_id']}", "Mandatory item",
                     f"Mandatory item {m['rule_id']} (rule not loaded in v0.1)",
                     "PM confirms the mandatory finding is addressed per spec", cls, findings=[finding]))

    # 3. core template
    g1_11 = lib.settings.get("g1_11_class", "Standard")
    for c in lib.core:
        cls = g1_11 if c["id"] == "G1-11" else "Standard"
        owner, fb = res.email(c["owner_role"])
        put(Item(pc, "G1", c["id"], "Core template", c["item"], c["criterion"], cls,
                 owner_email=owner, approver_role=f"Owner: {c['owner_role']}", role_fallback=fb))

    # 4. owners and approvers
    for it in bucket.values():
        if it.source == "Core template" and it.item_class == "Standard":
            continue
        it.owner_email = it.owner_email or res.email("BD POC")[0]
        if it.item_class == "Critical":
            rule = lib.rules.get(it.item_id)
            roles = (rule or {}).get("approver_roles") or ["Founders"]
            if it.item_id == "G1-11":
                roles = ["Founder"]
            it.approver_role = " + ".join(roles)
            it.approver_email, it.role_fallback = res.email(roles[0])
        elif it.item_class == "Note":
            it.approver_role = "Receiving POC"
            it.approver_email, it.role_fallback = res.receiver(it.gate)

    items = sorted(bucket.values(), key=lambda i: (i.gate, i.source != "Core template", i.item_id))
    return items, log
