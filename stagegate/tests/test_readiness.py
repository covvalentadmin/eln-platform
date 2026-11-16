from stagegate.readiness import evaluate


def rec(item_id, cls, status, gate="G1", hard="No", sup="No"):
    return {"item_id": item_id, "item_class": cls, "item_status": status, "gate": gate, "hard_stop": hard, "superseded": sup}


def test_red_on_undecided_or_rejected_critical():
    assert evaluate([rec("DF-S2", "Critical", "Awaiting decision")], "G1")["traffic_light"] == "Red"
    assert evaluate([rec("DF-S2", "Critical", "Reject")], "G1")["traffic_light"] == "Red"


def test_red_on_open_hard_stop_at_any_gate():
    r = evaluate([rec("DF-T1", "Critical", "Awaiting decision", gate="G3", hard="Yes"),
                  rec("G1-01", "Standard", "Done")], "G1")
    assert r["traffic_light"] == "Red" and r["blockers"].startswith("HARD STOP: DF-T1")


def test_hard_stop_listed_once_and_open_critical_is_union():
    r = evaluate([rec("DF-R5", "Critical", "Awaiting decision", hard="Yes"),
                  rec("DF-S2", "Critical", "Awaiting decision", hard="Yes"),
                  rec("DF-G1", "Critical", "Awaiting decision"),
                  rec("DF-T1", "Critical", "Awaiting decision", gate="G3", hard="Yes"),
                  rec("G1-01", "Standard", "Open")], "G1")
    assert r["blockers"] == "HARD STOP: DF-R5, DF-S2, DF-T1 | Critical: DF-G1 | Standard: G1-01"
    assert r["open_critical"] == 4  # union of G1 Criticals and hard stops at any gate
    only_hard = evaluate([rec("DF-R5", "Critical", "Awaiting decision", hard="Yes")], "G1")
    assert only_hard["blockers"] == "HARD STOP: DF-R5" and only_hard["open_critical"] == 1


def test_amber_when_criticals_decided_but_items_open():
    r = evaluate([rec("DF-S2", "Critical", "Approve with conditions"),
                  rec("G1-02", "Standard", "Open"),
                  rec("DF-R3", "Note", "Query")], "G1")
    assert r["traffic_light"] == "Amber"
    assert (r["open_critical"], r["open_standard"], r["unacked_notes"]) == (0, 1, 1)
    assert r["gate_ready"] == "No"


def test_ready_when_all_closed_and_superseded_ignored():
    r = evaluate([rec("DF-S2", "Critical", "Approve"),
                  rec("G1-02", "Standard", "Done"),
                  rec("DF-R3", "Note", "Taken into account"),
                  rec("DF-S5", "Critical", "Awaiting decision", sup="Yes"),
                  rec("DF-R6", "Critical", "Awaiting decision", gate="G2")], "G1")
    assert r["traffic_light"] == "Ready" and r["gate_ready"] == "Yes" and r["blockers"] == "None"
