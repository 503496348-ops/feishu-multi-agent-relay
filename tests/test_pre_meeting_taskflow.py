import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pre_meeting_taskflow import EvidencePacket, IntelLane, build_pre_meeting_plan, validate_evidence_packets


def test_pre_meeting_plan_creates_four_manager_only_lanes():
    plan = build_pre_meeting_plan("Ada Lovelace", "评估合作", signal_window_days=60)

    assert len(plan.tasks) == 4
    assert {task.lane for task in plan.tasks} == set(IntelLane)
    assert all(task.visibility == "manager_only" for task in plan.tasks)
    assert "60 天" in plan.manager_prompt()


def test_evidence_gate_requires_all_lanes_and_no_blockers():
    packets = [
        EvidencePacket(lane, f"{lane.value} summary", (f"https://source.example/{lane.value}",))
        for lane in IntelLane
    ]
    assert validate_evidence_packets(packets)["complete"] is True

    incomplete = packets[:-1] + [EvidencePacket(IntelLane.BUSINESS_ANGLE, "", ())]
    result = validate_evidence_packets(incomplete)
    assert result["complete"] is False
    assert "business_angle" in result["missing_lanes"]
