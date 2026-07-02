"""Pre-meeting intelligence task flow for multi-agent teams.

The flow converts a person-meeting objective into role-scoped worker tasks and
checks that returned evidence is usable before a manager composes the outward
brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class IntelLane(str, Enum):
    SELF_NARRATIVE = "self_narrative"
    OUTSIDE_READ = "outside_read"
    RECENT_EVENTS = "recent_events"
    BUSINESS_ANGLE = "business_angle"


@dataclass(frozen=True)
class IntelTask:
    lane: IntelLane
    worker_role: str
    objective: str
    required_evidence: tuple[str, ...]
    visibility: str = "manager_only"


@dataclass(frozen=True)
class EvidencePacket:
    lane: IntelLane
    summary: str
    sources: tuple[str, ...]
    quotes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def is_actionable(self) -> bool:
        return bool(self.summary.strip()) and len({s for s in self.sources if s.strip()}) >= 1


@dataclass(frozen=True)
class MeetingIntelPlan:
    person: str
    context: str
    signal_window_days: int = 90
    tasks: tuple[IntelTask, ...] = field(default_factory=tuple)

    def manager_prompt(self) -> str:
        return (
            f"为 {self.person} 生成会前情报，背景：{self.context or '通用会面'}。"
            f"时间窗：最近 {self.signal_window_days} 天。主持者只汇总证据、冲突和可开口话术。"
        )


def build_pre_meeting_plan(person: str, context: str = "", signal_window_days: int = 90) -> MeetingIntelPlan:
    if not person.strip():
        raise ValueError("person is required")
    tasks = (
        IntelTask(
            IntelLane.SELF_NARRATIVE,
            "自述线研究员",
            "查找目标本人近期公开表达、访谈、文章和个人主页更新，按时间倒序提取叙事变化。",
            ("发布日期", "原话摘录", "可访问链接"),
        ),
        IntelTask(
            IntelLane.OUTSIDE_READ,
            "旁观线研究员",
            "查找社区、用户、同行和媒体如何评价目标，重点标出与自述不一致的地方。",
            ("评价来源", "情绪方向", "触发事件"),
        ),
        IntelTask(
            IntelLane.RECENT_EVENTS,
            "事件线研究员",
            "整理最近窗口内的产品、融资、争议、演讲、任命等关键事件。",
            ("日期", "事件", "信源"),
        ),
        IntelTask(
            IntelLane.BUSINESS_ANGLE,
            "业务线研究员",
            "站在本次会面目的下提炼合作抓手、风险点和三句可直接开口的话术。",
            ("业务关联", "可开口问题", "风险提示"),
        ),
    )
    return MeetingIntelPlan(person=person.strip(), context=context.strip(), signal_window_days=signal_window_days, tasks=tasks)


def validate_evidence_packets(packets: Sequence[EvidencePacket]) -> dict[str, object]:
    seen = {packet.lane for packet in packets if packet.is_actionable()}
    missing = [lane.value for lane in IntelLane if lane not in seen]
    blockers = [blocker for packet in packets for blocker in packet.blockers]
    return {
        "complete": not missing and not blockers,
        "missing_lanes": missing,
        "blockers": blockers,
        "actionable_packets": len(seen),
    }
